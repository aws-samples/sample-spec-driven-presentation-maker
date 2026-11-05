// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Process Manager — manages multiple kiro-cli acp child processes,
 * keyed by sessionId. Enables background processing: switching decks
 * does not interrupt running agents.
 *
 * A new chat's process is registered under the client-generated id and under
 * its kiro session id (the one saved to the deck's `.session`), so reopening the
 * deck reuses the live process instead of loading the session into a second
 * kiro-cli, which the first one still locks.
 *
 * Max MAX_PROCESSES concurrent processes. Idle processes are evicted LRU.
 */
import { spawn, type ChildProcess } from "child_process"
import path from "path"
import { DECK_ROOT, resolveDeckDir } from "./deck-paths"
import { getActiveAgent, type AgentConfig } from "./acp-adapter"
import { syncToAgentsDir } from "./agents-sync"
import type { ForkSessionPhase, ForkSessionPhaseDetail, SessionOrigin } from "./kiro-sessions.types"
import { watchMcpServerReady } from "./mcp-ready"
import { SessionBusyError } from "./sessionErrors"
import { AgentTimeoutError, TURN_END, TURN_ERROR } from "./turnErrors"

export { DECK_ROOT }
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
const MAX_PROCESSES = 3
/** Matches the sdpm server's `timeout` in the ACP agent definitions. */
const MCP_READY_TIMEOUT_MS = 120_000
/**
 * Setup requests that must not hang an invoke forever. session/new and session/load can wait
 * for the agent's MCP servers (their own timeout is MCP_READY_TIMEOUT_MS) and session/load
 * replays the whole history first, so they get that plus a margin. session/prompt has none:
 * a turn lasts as long as the agent works, and Stop ends it.
 */
const INITIALIZE_TIMEOUT_MS = 30_000
const SESSION_SETUP_TIMEOUT_MS = MCP_READY_TIMEOUT_MS + 60_000
/** JSON-RPC "Method not found", the answer to agent requests this client does not implement. */
const METHOD_NOT_FOUND = -32601

type PendingResolve = (value: unknown) => void
interface PendingRequest {
  resolve: PendingResolve
  reject: (reason?: unknown) => void
}
type NotifyListener = (msg: Record<string, unknown>) => void

interface RequestOptions {
  timeoutMs?: number
  signal?: AbortSignal
}

interface SpawnProcessOptions {
  setMode?: boolean
  onPhase?: (phase: ForkSessionPhase, detail?: ForkSessionPhaseDetail) => void
  signal?: AbortSignal
}

interface ProcessState {
  child: ChildProcess
  deckId: string
  sessionId: string | null
  agentName: string
  requestId: number
  pending: Map<number, PendingRequest>
  listeners: Set<NotifyListener>
  lineBuffer: string
  running: boolean
  /** The child has exited (or failed to spawn); requests to it fail at once. */
  exited: boolean
  /** A session/prompt request has been sent and has not been answered yet. */
  promptInFlight: boolean
  /** JSON-RPC id of the current turn's session/prompt; its response (result or error) ends the turn. */
  promptRequestId: number | null
  notifications: { id: number; msg: Record<string, unknown> }[]
  eventIdCounter: number
  lastActivity: number
  /** Sub-agent sessions seen during the current turn; used only as session/cancel targets. */
  subSessionIds: Set<string>
}

/** Map keyed by sessionId; one process may sit under several keys (client id and kiro session id). */
const processes = new Map<string, ProcessState>()
export const pendingOrigins = new Map<string, SessionOrigin>()

// Model info (shared, populated from first process)
export interface AcpModel { modelId: string; name: string; description?: string }
let currentModelId = ""
let availableModels: AcpModel[] = []

// ── Per-process helpers ──

function writeMessage(ps: ProcessState, msg: Record<string, unknown>): void {
  if (ps.exited) return
  ps.child.stdin!.write(JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n")
}

/** Buffer an event for /stream reconnects and hand it to every listener. */
function emit(ps: ProcessState, msg: Record<string, unknown>): void {
  ps.notifications.push({ id: ++ps.eventIdCounter, msg })
  if (ps.notifications.length > 2000) ps.notifications.shift()
  for (const fn of ps.listeners) fn(msg)
}

/** The turn started by sendPrompt is over: release the session and tell the listeners. */
function endTurn(ps: ProcessState, event: Record<string, unknown>): void {
  ps.promptRequestId = null
  ps.running = false
  ps.subSessionIds.clear()
  emit(ps, { ...event, params: { sessionId: ps.sessionId, ...(event.params as Record<string, unknown>) } })
}

interface PermissionOption { optionId?: string; kind?: string }

/**
 * Answer a request kiro-cli sends to this client. Its id is kiro-cli's own and may equal one of
 * ours, so it is never matched against our pending requests. Permission requests are approved
 * with the offered option of kind allow_once (else allow_always): the optionId comes from the
 * request, never a fixed string, since V2 and V3 name their options differently. Anything else
 * is answered with Method not found, as JSON-RPC asks, instead of leaving kiro-cli waiting.
 */
function answerAgentRequest(ps: ProcessState, msg: Record<string, unknown>): void {
  const method = msg.method as string
  if (method === "session/request_permission") {
    const options = ((msg.params as Record<string, unknown> | undefined)?.options ?? []) as PermissionOption[]
    const pick = options.find((o) => o.kind === "allow_once")
      ?? options.find((o) => o.kind === "allow_always")
      ?? options.find((o) => o.kind === "reject_once")
    const outcome = pick?.optionId ? { outcome: "selected", optionId: pick.optionId } : { outcome: "cancelled" }
    writeMessage(ps, { id: msg.id, result: { outcome } })
    return
  }
  writeMessage(ps, { id: msg.id, error: { code: METHOD_NOT_FOUND, message: `Method not found: ${method}` } })
}

function handleLine(ps: ProcessState, line: string) {
  if (!line.trim()) return
  let msg: Record<string, unknown>
  try { msg = JSON.parse(line) } catch { return }

  // A request from kiro-cli carries a method and an id.
  if (msg.method !== undefined && msg.id != null) {
    answerAgentRequest(ps, msg)
    return
  }

  // A response to one of our requests. Only the answer to this turn's session/prompt ends the
  // turn (kiro-cli sends no turn_end for sub-agent sessions); an error answer to any other
  // request (set_config_option, a steer) rejects that request alone.
  if (msg.id != null) {
    const pending = ps.pending.get(msg.id as number)
    if (!pending) return
    ps.pending.delete(msg.id as number)
    let failure: Error | null = null
    if (msg.error) {
      const error = msg.error as { message?: string; data?: unknown }
      // kiro-cli puts the actual cause in `data` ("Internal error" alone is useless in logs)
      const detail = error.data === undefined ? "" : `: ${typeof error.data === "string" ? error.data : JSON.stringify(error.data)}`
      failure = new Error(`${error.message || "ACP request failed"}${detail}`)
    }
    if (msg.id === ps.promptRequestId) {
      const result = msg.result as { stopReason?: string } | undefined
      endTurn(ps, failure
        ? { method: TURN_ERROR, params: { message: failure.message } }
        : { method: TURN_END, params: { stopReason: result?.stopReason ?? "end_turn" } })
    }
    if (failure) pending.reject(failure)
    else pending.resolve(msg.result)
    return
  }

  // Buffer notifications
  if (msg.method === "session/update" || msg.method === "_kiro.dev/session/update") {
    const p = msg.params as Record<string, unknown>
    const sid = p?.sessionId as string
    // Only a turn's own updates name sub-agents; session/load replays the loaded
    // session under its id before ps.sessionId switches to it.
    if (sid && sid !== ps.sessionId && ps.promptRequestId !== null) ps.subSessionIds.add(sid)
    // A sub-agent that reports turn_end no longer needs a cancel
    const upd = p?.update as Record<string, unknown> | undefined
    const updType = upd?.sessionUpdate as string | undefined
    if ((updType === "turn_end" || updType === "end_turn") && sid && sid !== ps.sessionId) {
      ps.subSessionIds.delete(sid)
    }
    emit(ps, msg)
    return
  }

  for (const fn of ps.listeners) fn(msg)
}

function startRequest(
  ps: ProcessState,
  method: string,
  params: Record<string, unknown> = {},
  opts: RequestOptions = {},
): { id: number; response: Promise<unknown> } {
  if (!ps.child) throw new Error("Process not running")
  const id = ++ps.requestId
  const response = new Promise<unknown>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const settle = () => {
      if (timer) clearTimeout(timer)
      opts.signal?.removeEventListener("abort", onAbort)
      ps.pending.delete(id)
    }
    const onAbort = () => { settle(); reject(new DOMException("Request cancelled", "AbortError")) }
    ps.pending.set(id, {
      resolve: (value) => { settle(); resolve(value) },
      reject: (reason) => { settle(); reject(reason) },
    })
    if (ps.exited) { settle(); reject(new Error("ACP process has exited")); return }
    if (opts.timeoutMs) timer = setTimeout(() => { settle(); reject(new AgentTimeoutError(method, opts.timeoutMs!)) }, opts.timeoutMs)
    if (opts.signal?.aborted) onAbort()
    else opts.signal?.addEventListener("abort", onAbort, { once: true })
  })
  writeMessage(ps, { id, method, params })
  return { id, response }
}

function rpcRequestTo(ps: ProcessState, method: string, params: Record<string, unknown> = {}, opts?: RequestOptions): Promise<unknown> {
  return startRequest(ps, method, params, opts).response
}

function rpcNotifyTo(ps: ProcessState, method: string, params: Record<string, unknown> = {}): void {
  if (!ps.child) return
  writeMessage(ps, { method, params })
}

/** Ensure agents/ has files (first launch before Settings is opened). */
async function spawnProcess(
  agentName: string,
  existingSessionId?: string,
  opts: SpawnProcessOptions = {},
  adapter?: AgentConfig,
): Promise<ProcessState> {
  if (opts.signal?.aborted) throw new DOMException("Fork cancelled", "AbortError")
  opts.onPhase?.("starting")
  // Re-derive .kiro/agents/ from the acp-agents catalog + user selection on
  // every spawn (idempotent, all-or-nothing) — a `git pull` that updates the
  // catalog takes effect on the next spawn. If the derivation fails, the
  // spawn fails: launching from silently stale agent files is the exact bug
  // this re-derivation exists to prevent.
  syncToAgentsDir()
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
  const abortSpawn = () => child.kill()
  opts.signal?.addEventListener("abort", abortSpawn, { once: true })

  const ps: ProcessState = {
    child, deckId: "", sessionId: null, agentName,
    requestId: 0, pending: new Map(), listeners: new Set(),
    lineBuffer: "", running: false, exited: false, promptInFlight: false, promptRequestId: null, notifications: [], eventIdCounter: 0,
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
  // A write racing the exit (a Stop just as kiro-cli dies) fails with EPIPE; the exit handles it.
  child.stdin!.on("error", (error) => console.warn("[acp] stdin: %s", error.message))

  // The process is gone: fail what waits on it, end a running turn with an error the bridge
  // forwards (otherwise the chat would spin forever), and drop it from the map.
  const onExit = (code: number | null) => {
    if (ps.exited) return
    ps.exited = true
    console.log("[acp close] sessionId=%s code=%s", ps.sessionId, code)
    for (const pending of [...ps.pending.values()]) pending.reject(new Error(`ACP process exited with code ${code}`))
    ps.pending.clear()
    if (ps.promptInFlight) endTurn(ps, { method: TURN_ERROR, params: { code: "agent_exited", message: `kiro-cli exited with code ${code}` } })
    forgetProcess(ps)
  }
  child.on("close", onExit)
  child.on("error", (error) => {
    console.warn("[acp] process error: %s", error.message)
    if (child.pid === undefined) onExit(null) // spawn failed (kiro-cli not found); no close follows
  })

  try {
    // Initialize ACP
    await rpcRequestTo(ps, "initialize", {
      protocolVersion: 1,
      clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
      clientInfo: { name: "sdpm-local", version: "0.1.0" },
    }, { timeoutMs: INITIALIZE_TIMEOUT_MS, signal: opts.signal })

    // Create session
    const result = await rpcRequestTo(ps, "session/new", {
      cwd: MCP_LOCAL_DIR,
      mcpServers: [],
      agent: agentName,
    }, { timeoutMs: SESSION_SETUP_TIMEOUT_MS, signal: opts.signal }) as Record<string, unknown>
    ps.sessionId = result.sessionId as string

    // Restore existing session context if provided (Obsidian agent-client pattern)
    if (existingSessionId) {
      let replayed = 0
      let lastReported = 0
      let lastReportAt = Date.now()
      const replayListener: NotifyListener = (msg) => {
        if (msg.method !== "session/update" && msg.method !== "_kiro.dev/session/update") return
        const params = msg.params as Record<string, unknown> | undefined
        if (params?.sessionId !== existingSessionId) return
        replayed++
        const now = Date.now()
        if (replayed % 20 === 0 || now - lastReportAt >= 250) {
          lastReported = replayed
          lastReportAt = now
          opts.onPhase?.("loading", { replayed })
        }
      }

      opts.onPhase?.("loading", { replayed: 0 })
      ps.listeners.add(replayListener)
      // Watch from before session/load: the source agent may already carry the
      // sdpm server, and after set_mode its readiness can arrive before the reply.
      const sdpmReady = opts.setMode ? watchMcpServerReady(ps.listeners, existingSessionId) : null
      let loaded: { modes?: { availableModes?: { id: string }[] } }
      try {
        loaded = await rpcRequestTo(ps, "session/load", {
          sessionId: existingSessionId,
          cwd: MCP_LOCAL_DIR,
          mcpServers: [],
        }, { timeoutMs: SESSION_SETUP_TIMEOUT_MS, signal: opts.signal }) as { modes?: { availableModes?: { id: string }[] } }
      } catch (error) {
        sdpmReady?.dispose()
        throw error
      } finally {
        ps.listeners.delete(replayListener)
      }
      if (replayed !== lastReported) opts.onPhase?.("loading", { replayed })

      // After session/load, prompts must use the old sessionId
      processes.delete(ps.sessionId!)
      ps.sessionId = existingSessionId
      if (opts.setMode) {
        const available = loaded.modes?.availableModes
        if (!available?.some((mode) => mode.id === agentName)) {
          sdpmReady?.dispose()
          throw new Error(`mode ${agentName} unavailable`)
        }
        opts.onPhase?.("switching")
        try {
          await rpcRequestTo(ps, "session/set_mode", { sessionId: existingSessionId, modeId: agentName }, { timeoutMs: SESSION_SETUP_TIMEOUT_MS, signal: opts.signal })
        } catch (error) {
          sdpmReady?.dispose()
          throw error
        }
        // set_mode replies before the new agent's MCP servers are up; the first
        // prompt (the continuation greeting) needs start_presentation.
        if (sdpmReady && !(await sdpmReady.wait(MCP_READY_TIMEOUT_MS, opts.signal))) {
          console.warn("[acp] sdpm MCP server not initialized after %dms (session %s)", MCP_READY_TIMEOUT_MS, existingSessionId)
        }
      }
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

    opts.signal?.removeEventListener("abort", abortSpawn)
    return ps
  } catch (error) {
    opts.signal?.removeEventListener("abort", abortSpawn)
    child.kill()
    throw error
  }
}

/** Remove every map key that refers to a process. */
function forgetProcess(ps: ProcessState): void {
  for (const [key, candidate] of processes) {
    if (candidate === ps) processes.delete(key)
  }
}

async function evictIfNeeded(): Promise<void> {
  const live = new Set(processes.values())
  if (live.size < MAX_PROCESSES) return
  let oldest: ProcessState | null = null
  for (const ps of live) {
    if (ps.running) continue
    if (!oldest || ps.lastActivity < oldest.lastActivity) oldest = ps
  }
  if (oldest) {
    oldest.child.kill()
    forgetProcess(oldest)
    await new Promise(r => setTimeout(r, 500))
  }
}

// ── Public API ──

/** Check if a live process exists for a sessionId. */
export function hasProcess(sessionId: string): boolean {
  return processes.has(sessionId)
}

/** Kill a process and remove every map key that refers to it. */
export function terminateProcess(sessionId: string): void {
  const ps = processes.get(sessionId)
    ?? Array.from(processes.values()).find((candidate) => candidate.sessionId === sessionId)
  if (!ps) return
  forgetProcess(ps)
  ps.child.kill()
}

/** Get or create a process for a sessionId. Restores context if existingSessionId provided. */
export async function getOrCreateProcess(
  sessionId: string,
  agentName: string = "sdpm-orchestrator",
  opts: SpawnProcessOptions = {},
): Promise<ProcessState> {
  let ps = processes.get(sessionId)
  if (ps) {
    ps.lastActivity = Date.now()
    return ps
  }
  // No live process — spawn new one and restore session context
  await evictIfNeeded()
  ps = await spawnProcess(agentName, sessionId, opts)
  processes.set(sessionId, ps)
  return ps
}

/** Spawn a brand-new process (no existing session). Returns the new sessionId. */
export async function createNewProcess(agentName: string = "sdpm-orchestrator"): Promise<ProcessState> {
  await evictIfNeeded()
  const ps = await spawnProcess(agentName)
  processes.set(ps.sessionId!, ps)
  return ps
}

/** Spawn a new process and register it under a client-provided key and its kiro session id. */
export async function createNewProcessFor(
  clientSessionId: string,
  agentName: string = "sdpm-orchestrator",
  opts: SpawnProcessOptions = {},
): Promise<ProcessState> {
  await evictIfNeeded()
  const ps = await spawnProcess(agentName, undefined, opts)
  processes.set(clientSessionId, ps)
  processes.set(ps.sessionId!, ps)
  return ps
}

/**
 * Send a prompt to a session's process.
 * Throws SessionBusyError while the process is still answering an earlier prompt
 * (the same session open in two panels or tabs); prompts are not queued.
 */
export async function sendPrompt(sessionId: string, text: string, agentName?: string): Promise<{ sessionId: string; subscribe: (fn: NotifyListener) => () => void; send: () => void }> {
  const ps = await getOrCreateProcess(sessionId, agentName || "sdpm-orchestrator")
  if (ps.promptInFlight) throw new SessionBusyError()
  ps.promptInFlight = true
  ps.running = true
  ps.subSessionIds.clear()
  ps.notifications = []; ps.eventIdCounter = 0
  ps.lastActivity = Date.now()

  return {
    sessionId: ps.sessionId!,
    subscribe: (fn: NotifyListener) => {
      ps.listeners.add(fn)
      return () => { ps.listeners.delete(fn) }
    },
    send: () => {
      const { id, response } = startRequest(ps, "session/prompt", {
        sessionId: ps.sessionId,
        prompt: [{ type: "text", text }],
      })
      ps.promptRequestId = id
      void response.catch(() => {
        // handleLine (an answer) or the exit handler (no answer) ends the turn for the listeners.
      }).finally(() => { ps.promptInFlight = false })
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

/** Save a fork's source metadata to the deck. */
export function saveOriginToDeck(deckId: string, origin: SessionOrigin): void {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir || !fs.existsSync(dir)) return
  fs.writeFileSync(path.join(dir, ".session-origin.json"), JSON.stringify(origin), "utf-8")
}

/** Read a fork's source metadata from the deck. */
export function readOriginFromDeck(deckId: string): SessionOrigin | null {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return null
  try { return JSON.parse(fs.readFileSync(path.join(dir, ".session-origin.json"), "utf-8")) as SessionOrigin } catch { return null }
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
    pendingOrigins.clear()
  })
}
