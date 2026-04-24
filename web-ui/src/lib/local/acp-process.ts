// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Process Manager — spawns and manages a single kiro-cli acp child process.
 *
 * Provides JSON-RPC request/response and notification subscription.
 * Singleton: one process shared across all API route invocations.
 */
import { spawn, type ChildProcess } from "child_process"
import path from "path"
import { DECK_ROOT, resolveDeckDir } from "./deck-paths"

export { DECK_ROOT }
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "mcp-local")

type PendingResolve = (value: unknown) => void
type NotifyListener = (msg: Record<string, unknown>) => void

let child: ChildProcess | null = null
let requestId = 0
let sessionId: string | null = null
const subSessionIds = new Set<string>()
const pending = new Map<number, PendingResolve>()
const listeners = new Set<NotifyListener>()
let lineBuffer = ""

function handleLine(line: string) {
  if (!line.trim()) return
  let msg: Record<string, unknown>
  try { msg = JSON.parse(line) } catch { return }

  // JSON-RPC response
  if (msg.id != null && pending.has(msg.id as number)) {
    const resolve = pending.get(msg.id as number)!
    pending.delete(msg.id as number)
    resolve(msg.result)
    // Also notify listeners for end_turn detection
    for (const fn of listeners) fn(msg)
    return
  }

  // Auto-approve permission requests
  if (msg.method === "session/request_permission") {
    const reqId = msg.id as string
    if (reqId && child) {
      child.stdin!.write(JSON.stringify({
        jsonrpc: "2.0", id: reqId, result: { outcome: { outcome: "selected", optionId: "allow_always" } },
      }) + "\n")
    }
    return
  }

  // Forward notifications to all listeners
  // Track subagent session IDs
  if (msg.method === "session/update" || msg.method === "_kiro.dev/session/update") {
    const p = msg.params as Record<string, unknown>
    const sid = p?.sessionId as string
    if (sid && sid !== sessionId) subSessionIds.add(sid)
  }
  for (const fn of listeners) fn(msg)
}

/** Send a JSON-RPC request and await the response. */
export function rpcRequest(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!child) throw new Error("ACP agent not started")
  const id = ++requestId
  const msg = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n"
  child.stdin!.write(msg)
  return new Promise((resolve) => { pending.set(id, resolve) })
}

/** Subscribe to JSON-RPC notifications. Returns unsubscribe function. */
export function subscribe(fn: NotifyListener): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** Send a fire-and-forget JSON-RPC notification (no id, no response). */
export function rpcNotify(method: string, params: Record<string, unknown> = {}): void {
  if (!child) return
  child.stdin!.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n")
}

/** Cancel the current session and all subagent sessions. */
export function cancelAll(): void {
  if (!child) return
  if (sessionId) {
    rpcNotify("session/cancel", { sessionId })
    for (const subId of subSessionIds) {
      rpcNotify("session/cancel", { sessionId: subId })
    }
    subSessionIds.clear()
  }
}
export function getSessionId(): string | null { return sessionId }

export interface AcpModel { modelId: string; name: string; description?: string }

let currentModelId = ""
let availableModels: AcpModel[] = []

/** Get available models (populated after ensureAgent). */
export function getModels(): { current: string; available: AcpModel[] } {
  return { current: currentModelId, available: availableModels }
}

/** Set a session config option (e.g. model selection). */
export async function setConfigOption(configId: string, value: string): Promise<void> {
  if (!child || !sessionId) return
  await rpcRequest("session/set_config_option", { sessionId, configId, value })
}

let currentAgentName = "sdpm-spec"

/** Ensure the ACP process is running and a session exists. */
export async function ensureAgent(agentName: string = "sdpm-spec"): Promise<void> {
  // If agent name changed, kill existing process to restart with new agent
  if (child && agentName !== currentAgentName) {
    const oldChild = child
    child = null
    sessionId = null
    pending.clear()
    listeners.clear()
    lineBuffer = ""
    oldChild.kill()
    // Wait for process to exit before spawning new one
    await new Promise<void>((resolve) => {
      oldChild.on("close", () => resolve())
      setTimeout(resolve, 3000) // fallback timeout
    })
  }
  if (child) return

  currentAgentName = agentName
  const mcpLocalDir = MCP_LOCAL_DIR

  child = spawn("kiro-cli", ["acp", "--agent", agentName], {
    cwd: mcpLocalDir,
    stdio: ["pipe", "pipe", "pipe"],
  })
  const newChild = child

  child.stdout!.setEncoding("utf-8")
  child.stdout!.on("data", (data: string) => {
    lineBuffer += data
    const lines = lineBuffer.split("\n")
    lineBuffer = lines.pop() || ""
    for (const l of lines) handleLine(l)
  })

  child.stderr!.setEncoding("utf-8")
  child.stderr!.on("data", (d: string) => console.warn("[acp stderr]", d))

  child.on("close", () => {
    // Only reset if this is still the active child (not replaced by a new spawn)
    if (child === newChild) {
      child = null
      sessionId = null
      pending.clear()
      listeners.clear()
    }
  })

  await rpcRequest("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
    clientInfo: { name: "sdpm-local", version: "0.1.0" },
  })

  const AGENT_NAME = agentName

  const result = await rpcRequest("session/new", { cwd: MCP_LOCAL_DIR, mcpServers: [], agent: AGENT_NAME }) as Record<string, unknown>
  sessionId = result.sessionId as string

  // Extract model info from session/new response
  const modelsData = result.models as { currentModelId?: string; availableModels?: AcpModel[] } | undefined
  if (modelsData) {
    currentModelId = modelsData.currentModelId || ""
    availableModels = (modelsData.availableModels || [])
      .filter(o => !o.description?.startsWith("[Internal]") && !o.description?.startsWith("[Deprecated]"))
  }

  // Model preference is managed client-side via /api/agent/models PUT
}

/** Create a new ACP session (for new chat). */
export async function newSession(agentName?: string): Promise<void> {
  const agent = agentName || currentAgentName
  const result = await rpcRequest("session/new", { cwd: MCP_LOCAL_DIR, mcpServers: [], agent }) as Record<string, unknown>
  sessionId = result.sessionId as string
}

/** Load an existing ACP session (replays history via session/update notifications). */
export async function loadSession(savedSessionId: string): Promise<void> {
  await ensureAgent()
  const result = await rpcRequest("session/load", { sessionId: savedSessionId, cwd: MCP_LOCAL_DIR, mcpServers: [] }) as Record<string, unknown> | undefined
  sessionId = (result?.sessionId as string) || savedSessionId
}

/** Save sessionId to deck's .session file. */
export function saveSessionToDeck(deckId: string): void {
  if (!sessionId) return
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
  process.on(sig, () => { child?.kill(); child = null })
}
