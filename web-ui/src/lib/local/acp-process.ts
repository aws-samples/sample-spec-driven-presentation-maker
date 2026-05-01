// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Process Manager — manages multiple kiro-cli acp child processes,
 * keyed by sessionId. Enables background processing: switching decks
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
  lastActivity: number
  subSessionIds: Set<string>
}

/** Map keyed by sessionId */
const processes = new Map<string, ProcessState>()

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
    // Detect subagent turn_end → remove from active set
    const upd = p?.update as Record<string, unknown> | undefined
    const updType = upd?.sessionUpdate as string | undefined
    if ((updType === "turn_end" || updType === "end_turn") && sid && sid !== ps.sessionId) {
      ps.subSessionIds.delete(sid)
    }
    ps.notifications.push({ id: ++ps.eventIdCounter, msg })
    if (ps.notifications.length > 2000) ps.notifications.shift()
  }

  // Detect end_turn
  if (msg.id != null && msg.result) {
    const r = msg.result as Record<string, unknown>
    if (r.stopReason === "end_turn" || r.stopReason === "cancelled") {
      if (ps.subSessionIds.size === 0) {
        ps.running = false
      }
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

async function spawnProcess(agentName: string, existingSessionId?: string, adapter?: AgentConfig): Promise<ProcessState> {
  const cfg = adapter || getActiveAgent()
  let args = [...cfg.args]
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
    child, deckId: "", sessionId: null, agentName,
    requestId: 0, pending: new Map(), listeners: new Set(),
    lineBuffer: "", running: false, notifications: [], eventIdCounter: 0,
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
  child.stderr!.on("data", (d: string) => console.warn("[acp] stderr: %s", d.trim()))

  child.on("close", (code) => {
    console.log("[acp close] sessionId=%s code=%s", ps.sessionId, code)
    if (ps.sessionId) processes.delete(ps.sessionId)
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

  // Restore existing session context if provided (Obsidian agent-client pattern)
  if (existingSessionId) {
    await rpcRequestTo(ps, "session/load", { sessionId: existingSessionId, cwd: MCP_LOCAL_DIR, mcpServers: [] })
    // After session/load, prompts must use the old sessionId
    processes.delete(ps.sessionId!)
    ps.sessionId = existingSessionId
  }

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
  let oldest: ProcessState | null = null
  for (const ps of processes.values()) {
    if (ps.running) continue
    if (!oldest || ps.lastActivity < oldest.lastActivity) oldest = ps
  }
  if (oldest) {
    oldest.child.kill()
    if (oldest.sessionId) processes.delete(oldest.sessionId)
    await new Promise(r => setTimeout(r, 500))
  }
}

// ── Public API ──

/** Check if a live process exists for a sessionId. */
export function hasProcess(sessionId: string): boolean {
  return processes.has(sessionId)
}

/** Get or create a process for a sessionId. Restores context if existingSessionId provided. */
export async function getOrCreateProcess(sessionId: string, agentName: string = "sdpm-spec"): Promise<ProcessState> {
  let ps = processes.get(sessionId)
  if (ps) {
    ps.lastActivity = Date.now()
    return ps
  }
  // No live process — spawn new one and restore session context
  await evictIfNeeded()
  ps = await spawnProcess(agentName, sessionId)
  processes.set(sessionId, ps)
  return ps
}

/** Spawn a brand-new process (no existing session). Returns the new sessionId. */
export async function createNewProcess(agentName: string = "sdpm-spec"): Promise<ProcessState> {
  await evictIfNeeded()
  const ps = await spawnProcess(agentName)
  processes.set(ps.sessionId!, ps)
  return ps
}

/** Spawn a new process and register it under a client-provided key. */
export async function createNewProcessFor(clientSessionId: string, agentName: string = "sdpm-spec"): Promise<ProcessState> {
  await evictIfNeeded()
  const ps = await spawnProcess(agentName)
  processes.set(clientSessionId, ps)
  return ps
}

/** Send a prompt to a session's process. */
export async function sendPrompt(sessionId: string, text: string, agentName?: string): Promise<{ sessionId: string; subscribe: (fn: NotifyListener) => () => void; send: () => void }> {
  const ps = await getOrCreateProcess(sessionId, agentName || "sdpm-spec")
  ps.running = true
  ps.notifications = []; ps.eventIdCounter = 0
  ps.lastActivity = Date.now()

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

/** Cancel a session's active prompt. */
export function cancelSession(sessionId: string): void {
  const ps = processes.get(sessionId)
  if (!ps) return
  if (ps.sessionId) {
    rpcNotifyTo(ps, "session/cancel", { sessionId: ps.sessionId })
    for (const subId of ps.subSessionIds) {
      rpcNotifyTo(ps, "session/cancel", { sessionId: subId })
    }
    ps.subSessionIds.clear()
  }
}

/** Cancel all processes (stop button with no specific session). */
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

/** Check if a session has a running process. */
export function isSessionRunning(sessionId: string): boolean {
  return processes.get(sessionId)?.running ?? false
}

/** Drain buffered notifications for a session. */
export function getBufferedEvents(sessionId: string, afterId?: number): { id: number; msg: Record<string, unknown> }[] {
  const ps = processes.get(sessionId)
  if (!ps) return []
  if (afterId == null) return [...ps.notifications]
  return ps.notifications.filter(e => e.id > afterId)
}

/** Subscribe to a session's process notifications. */
export function subscribeToSession(sessionId: string): { sessionId: string | null; subscribe: (fn: NotifyListener) => () => void } | null {
  const ps = processes.get(sessionId)
  if (!ps) return null
  return {
    sessionId: ps.sessionId,
    subscribe: (fn: NotifyListener) => {
      ps.listeners.add(fn)
      return () => { ps.listeners.delete(fn) }
    },
  }
}

export function getModels(): { current: string; available: AcpModel[] } {
  return { current: currentModelId, available: availableModels }
}

export async function setConfigOption(sessionId: string, configId: string, value: string): Promise<void> {
  const ps = processes.get(sessionId)
  if (!ps?.sessionId) return
  await rpcRequestTo(ps, "session/set_config_option", { sessionId: ps.sessionId, configId, value })
}

/** Save sessionId to deck's .session file. */
export function saveSessionToDeck(deckId: string, sessionId: string): void {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir || !fs.existsSync(dir)) return
  fs.writeFileSync(path.join(dir, ".session"), sessionId, "utf-8")
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
