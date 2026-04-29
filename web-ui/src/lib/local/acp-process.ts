// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Process Manager — manages multiple kiro-cli acp child processes,
 * one per active deck. Enables background processing: switching decks
 * does not interrupt running agents.
 *
 * Max MAX_PROCESSES concurrent processes. Idle processes are evicted LRU.
 */
import { spawn, type ChildProcess } from "child_process"
import path from "path"
import { DECK_ROOT, resolveDeckDir } from "./deck-paths"
import { getActiveAgent, type AgentConfig } from "./acp-adapter"

export { DECK_ROOT }
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "mcp-local")
const MAX_PROCESSES = 3

type PendingResolve = (value: unknown) => void
type NotifyListener = (msg: Record<string, unknown>) => void

interface ProcessState {
  child: ChildProcess
  deckId: string
  sessionId: string | null
  agentName: string
  requestId: number
  pending: Map<number, PendingResolve>
  listeners: Set<NotifyListener>
  lineBuffer: string
  running: boolean
  notifications: { id: number; msg: Record<string, unknown> }[]
  eventIdCounter: number
  // Server-side chat state — updated from notifications, saved to .chat.json
  chatMessages: Record<string, unknown>[]
  chatDirty: boolean
  lastActivity: number
  subSessionIds: Set<string>
}

const processes = new Map<string, ProcessState>()
let activeDeckId: string | null = null

// Model info (shared, populated from first process)
export interface AcpModel { modelId: string; name: string; description?: string }
let currentModelId = ""
let availableModels: AcpModel[] = []

// ── Per-process helpers ──

function handleLine(ps: ProcessState, line: string) {
  if (!line.trim()) return
  let msg: Record<string, unknown>
  try { msg = JSON.parse(line) } catch { return }

  // JSON-RPC response
  if (msg.id != null && ps.pending.has(msg.id as number)) {
    const resolve = ps.pending.get(msg.id as number)!
    ps.pending.delete(msg.id as number)
    resolve(msg.result)
    // Server-side chat state tracking — updates .chat.json independent of browser
  if (msg.method === "session/update" || msg.method === "_kiro.dev/session/update") {
    const p = msg.params as Record<string, unknown>
    const update = p?.update as Record<string, unknown>
    if (update) {
      const type = update.sessionUpdate as string
      const msgSid = p?.sessionId as string

      // Only track main session messages (not subagent)
      if (msgSid === ps.sessionId) {
        if (type === "agent_message_chunk") {
          const content = update.content as Record<string, unknown>
          if (content?.text) {
            // Append text to last assistant message
            let last = ps.chatMessages[ps.chatMessages.length - 1] as Record<string, unknown> | undefined
            if (!last || last.role !== "assistant") {
              last = { role: "assistant", content: "", toolUses: [], blocks: [] }
              ps.chatMessages.push(last)
            }
            last.content = (last.content as string || "") + (content.text as string)
            ps.chatDirty = true
          }
        }
        if (type === "tool_call" || type === "tool_call_chunk") {
          const toolCallId = (update.toolCallId || "") as string
          const title = (update.title || update.name || "") as string
          const name = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
          const input = (update.rawInput || update.input || {}) as Record<string, unknown>
          let last = ps.chatMessages[ps.chatMessages.length - 1] as Record<string, unknown> | undefined
          if (!last || last.role !== "assistant") {
            last = { role: "assistant", content: "", toolUses: [], blocks: [] }
            ps.chatMessages.push(last)
          }
          const toolUses = (last.toolUses as Record<string, unknown>[]) || []
          if (!toolUses.some(t => t.toolUseId === toolCallId)) {
            toolUses.push({ toolUseId: toolCallId, name, input, streamMessages: [] })
            last.toolUses = toolUses
            ps.chatDirty = true
          }
        }
        if (type === "tool_call_update") {
          const status = update.status as string
          const toolCallId = (update.toolCallId || "") as string
          if (status === "completed" || status === "error") {
            const last = ps.chatMessages[ps.chatMessages.length - 1] as Record<string, unknown> | undefined
            if (last) {
              const toolUses = (last.toolUses as Record<string, unknown>[]) || []
              const tool = toolUses.find(t => t.toolUseId === toolCallId)
              if (tool) {
                tool.status = status === "completed" ? "success" : "error"
                ps.chatDirty = true
              }
            }
          }
        }
      }

      // Track subagent toolStream events
      if (msgSid !== ps.sessionId && ps.subSessionIds.has(msgSid)) {
        const last = ps.chatMessages[ps.chatMessages.length - 1] as Record<string, unknown> | undefined
        if (last) {
          const toolUses = (last.toolUses as Record<string, unknown>[]) || []
          // Find compose_slides tool (the one with streamMessages)
          const composeTool = toolUses.find(t => (t.streamMessages as unknown[])?.length >= 0 && (t.name === "compose_slides" || t.name === "subagent" || (t.name as string)?.includes("subagent")))
          if (composeTool) {
            const sm = (composeTool.streamMessages as Record<string, unknown>[]) || []
            if (type === "tool_call") {
              const title = (update.title || "") as string
              const toolName = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
              sm.push({ tool: toolName, group: 0, toolUseId: update.toolCallId })
              composeTool.streamMessages = sm
              ps.chatDirty = true
            }
          }
        }
      }
    }
  }

  // Periodically flush dirty chat to .chat.json
  if (ps.chatDirty && ps.deckId && !ps.deckId.startsWith("_new_")) {
    ps.chatDirty = false
    saveChatToDeck(ps.deckId, ps.chatMessages)
  }

  for (const fn of ps.listeners) fn(msg)
    return
  }

  // Auto-approve permission requests
  if (msg.method === "session/request_permission") {
    const reqId = msg.id as string
    if (reqId && ps.child) {
      ps.child.stdin!.write(JSON.stringify({
        jsonrpc: "2.0", id: reqId, result: { outcome: { outcome: "selected", optionId: "allow_always" } },
      }) + "\n")
    }
    return
  }

  // Buffer notifications
  if (msg.method === "session/update" || msg.method === "_kiro.dev/session/update") {
    const p = msg.params as Record<string, unknown>
    const sid = p?.sessionId as string
    if (sid && sid !== ps.sessionId) ps.subSessionIds.add(sid)
    ps.notifications.push({ id: ++ps.eventIdCounter, msg })
    if (ps.notifications.length > 2000) ps.notifications.shift()
  }

  // Detect end_turn
  if (msg.id != null && msg.result) {
    const r = msg.result as Record<string, unknown>
    if (r.stopReason === "end_turn" || r.stopReason === "cancelled") {

      ps.running = false
    }
  }

  for (const fn of ps.listeners) fn(msg)
}

function rpcRequestTo(ps: ProcessState, method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!ps.child) throw new Error("Process not running")
  const id = ++ps.requestId
  ps.child.stdin!.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n")
  return new Promise((resolve) => { ps.pending.set(id, resolve) })
}

function rpcNotifyTo(ps: ProcessState, method: string, params: Record<string, unknown> = {}): void {
  if (!ps.child) return
  ps.child.stdin!.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n")
}

async function spawnProcess(deckId: string, agentName: string, adapter?: AgentConfig): Promise<ProcessState> {
  const cfg = adapter || getActiveAgent()
  // For kiro-cli, replace agent name in args if agentFlag is set
  let args = [...cfg.args]
  // For kiro-cli, replace agent name in args (--agent <name>)
  const flagIdx = args.indexOf("--agent")
  if (flagIdx >= 0 && flagIdx + 1 < args.length) {
    args[flagIdx + 1] = agentName
  }
  const child = spawn(cfg.path, args, {
    cwd: MCP_LOCAL_DIR,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, ...cfg.env, SDPM_OUTPUT_DIR: DECK_ROOT, SDPM_DECK_ROOT: DECK_ROOT },
  })

  const ps: ProcessState = {
    child, deckId, sessionId: null, agentName,
    requestId: 0, pending: new Map(), listeners: new Set(),
    lineBuffer: "", running: false, notifications: [], eventIdCounter: 0,
    chatMessages: [], chatDirty: false,
    lastActivity: Date.now(), subSessionIds: new Set(),
  }

  child.stdout!.setEncoding("utf-8")
  child.stdout!.on("data", (data: string) => {
    ps.lineBuffer += data
    const lines = ps.lineBuffer.split("\n")
    ps.lineBuffer = lines.pop() || ""
    for (const l of lines) handleLine(ps, l)
  })

  child.stderr!.setEncoding("utf-8")
  child.stderr!.on("data", (d: string) => console.warn(`[acp:${deckId}] stderr:`, d.trim()))

  child.on("close", () => {
    processes.delete(deckId)
  })

  // Initialize ACP
  await rpcRequestTo(ps, "initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
    clientInfo: { name: "sdpm-local", version: "0.1.0" },
  })

  // Create session
  const result = await rpcRequestTo(ps, "session/new", { cwd: MCP_LOCAL_DIR, mcpServers: [], agent: agentName }) as Record<string, unknown>
  ps.sessionId = result.sessionId as string

  // Extract model info from first process
  if (!availableModels.length) {
    const modelsData = result.models as { currentModelId?: string; availableModels?: AcpModel[] } | undefined
    if (modelsData) {
      currentModelId = modelsData.currentModelId || ""
      availableModels = (modelsData.availableModels || [])
        .filter(o => !o.description?.startsWith("[Internal]") && !o.description?.startsWith("[Deprecated]"))
    }
  }

  return ps
}

async function evictIfNeeded(): Promise<void> {
  if (processes.size < MAX_PROCESSES) return
  // Find oldest idle process (not running, not active)
  let oldest: ProcessState | null = null
  for (const ps of processes.values()) {
    if (ps.running || ps.deckId === activeDeckId) continue
    if (!oldest || ps.lastActivity < oldest.lastActivity) oldest = ps
  }
  if (oldest) {
    oldest.child.kill()
    processes.delete(oldest.deckId)
    // Wait briefly for cleanup
    await new Promise(r => setTimeout(r, 500))
  }
}

// ── Public API ──

/** Get or create a process for a deck. */
export async function getProcess(deckId: string, agentName: string = "sdpm-spec"): Promise<ProcessState> {
  let ps = processes.get(deckId)
  if (ps) {
    ps.lastActivity = Date.now()
    return ps
  }
  await evictIfNeeded()
  ps = await spawnProcess(deckId, agentName)
  processes.set(deckId, ps)
  activeDeckId = deckId
  return ps
}

/** Get or create a process for a new deck (no deckId yet). Returns temp key. */
export async function newProcess(agentName: string = "sdpm-spec"): Promise<{ ps: ProcessState; tempKey: string }> {
  // Reuse existing idle temp process if available
  for (const [key, ps] of processes) {
    if (key.startsWith("_new_") && !ps.running && ps.agentName === agentName) {
      activeDeckId = key
      return { ps, tempKey: key }
    }
  }
  const tempKey = `_new_${Date.now()}`
  await evictIfNeeded()
  const ps = await spawnProcess(tempKey, agentName)
  processes.set(tempKey, ps)
  activeDeckId = tempKey
  return { ps, tempKey }
}

/** Re-key a temp process to a real deckId. */
export function associateDeck(tempKey: string, deckId: string): void {
  const ps = processes.get(tempKey)
  if (!ps) return
  processes.delete(tempKey)
  ps.deckId = deckId
  processes.set(deckId, ps)
  if (activeDeckId === tempKey) activeDeckId = deckId
}

/** Send a prompt to a deck's process. */
export async function sendPrompt(deckId: string, text: string, agentName?: string): Promise<{ sessionId: string; subscribe: (fn: NotifyListener) => () => void; send: () => void }> {
  const ps = await getProcess(deckId, agentName)
  ps.running = true
  ps.notifications = []; ps.eventIdCounter = 0
  ps.lastActivity = Date.now()

  // Initialize server-side chat state with user message
  ps.chatMessages = [{ role: "user", content: text, toolUses: [] }]
  ps.chatDirty = false

  return {
    sessionId: ps.sessionId!,
    subscribe: (fn: NotifyListener) => {
      ps.listeners.add(fn)
      return () => { ps.listeners.delete(fn) }
    },
    send: () => {
      rpcRequestTo(ps, "session/prompt", {
        sessionId: ps.sessionId,
        prompt: [{ type: "text", text }],
      })
    },
  }
}

/** Cancel a deck's active prompt. */
export function cancelDeck(deckId: string): void {
  const ps = processes.get(deckId)
  if (!ps) return
  if (ps.sessionId) {
    rpcNotifyTo(ps, "session/cancel", { sessionId: ps.sessionId })
    for (const subId of ps.subSessionIds) {
      rpcNotifyTo(ps, "session/cancel", { sessionId: subId })
    }
    ps.subSessionIds.clear()
  }
}

/** Cancel all processes (stop button with no specific deck). */
export function cancelAll(): void {
  for (const ps of processes.values()) {
    if (ps.running && ps.sessionId) {
      rpcNotifyTo(ps, "session/cancel", { sessionId: ps.sessionId })
      for (const subId of ps.subSessionIds) {
        rpcNotifyTo(ps, "session/cancel", { sessionId: subId })
      }
      ps.subSessionIds.clear()
    }
  }
}

/** Check if a deck has a running process. */
export function isSessionRunning(deckId: string): boolean {
  return processes.get(deckId)?.running ?? false
}

/** Mark running state. */
export function markSessionRunning(deckId: string, running: boolean): void {
  const ps = processes.get(deckId)
  if (ps) ps.running = running
}

/** Drain buffered notifications for a deck. */
export function getBufferedEvents(deckId: string, afterId?: number): { id: number; msg: Record<string, unknown> }[] {
  const ps = processes.get(deckId)
  if (!ps) return []
  if (afterId == null) return [...ps.notifications]
  return ps.notifications.filter(e => e.id > afterId)
}

/** Subscribe to a deck's process notifications. */
export function subscribeToDeck(deckId: string): { sessionId: string | null; subscribe: (fn: NotifyListener) => () => void } | null {
  const ps = processes.get(deckId)
  if (!ps) return null
  return {
    sessionId: ps.sessionId,
    subscribe: (fn: NotifyListener) => {
      ps.listeners.add(fn)
      return () => { ps.listeners.delete(fn) }
    },
  }
}

/** Get session ID for a deck. */
export function getSessionId(deckId?: string): string | null {
  const id = deckId || activeDeckId
  if (!id) return null
  return processes.get(id)?.sessionId ?? null
}

export function getActiveDeckId(): string | null { return activeDeckId }
export function setActiveDeckId(id: string): void { activeDeckId = id }

export function getModels(): { current: string; available: AcpModel[] } {
  return { current: currentModelId, available: availableModels }
}

export async function setConfigOption(deckId: string, configId: string, value: string): Promise<void> {
  const ps = processes.get(deckId)
  if (!ps?.sessionId) return
  await rpcRequestTo(ps, "session/set_config_option", { sessionId: ps.sessionId, configId, value })
}

/** Save sessionId to deck's .session file. */
export function saveSessionToDeck(deckId: string): void {
  const sid = getSessionId(deckId)
  if (!sid) return
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir || !fs.existsSync(dir)) return
  fs.writeFileSync(path.join(dir, ".session"), sid, "utf-8")
}

/** Read sessionId from deck's .session file. */
export function readSessionFromDeck(deckId: string): string | null {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return null
  try { return fs.readFileSync(path.join(dir, ".session"), "utf-8").trim() } catch { return null }
}

/** Save chat messages to deck's .chat.json file. */
export function saveChatToDeck(deckId: string, messages: unknown[]): void {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir || !fs.existsSync(dir)) return
  fs.writeFileSync(path.join(dir, ".chat.json"), JSON.stringify(messages), "utf-8")
}

/** Read chat messages from deck's .chat.json file. */
export function readChatFromDeck(deckId: string): unknown[] {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return []
  try { return JSON.parse(fs.readFileSync(path.join(dir, ".chat.json"), "utf-8")) } catch { return [] }
}

// Cleanup on process exit
for (const sig of ["exit", "SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => {
    for (const ps of processes.values()) ps.child.kill()
    processes.clear()
  })
}
