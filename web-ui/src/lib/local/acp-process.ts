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
 * Each process is a transport connection (acp/transport.ts), the engine's session for it
 * (acp/engine.ts) and the chat's conversation model (conversation/). Every kiro-cli notification
 * goes through the engine's `translate`, its MCP readiness events to the setup's MCP watch and
 * the rest to the conversation model, whose chat events are numbered and buffered here (the SSE
 * `id:`, the same for live and replayed events) and handed to the listeners. A deck a tool
 * result names gets the session's `.session` (and a fork's origin) here, whether or not a
 * browser is listening.
 *
 * Max MAX_PROCESSES concurrent processes. Idle processes are evicted LRU.
 */
import path from "path"
import { DECK_ROOT, resolveDeckDir } from "./deck-paths"
import { getActiveAgent } from "./acp-adapter"
import { syncToAgentsDir } from "./agents-sync"
import { adapterFor, type AcpModel, type EngineCapabilities, type EngineId, type EngineSession } from "./acp/engine"
import type { InitializeResponse, PromptResponse } from "./acp/schema"
import { spawnAcp, type AcpAnswer, type AcpConnection } from "./acp/transport"
import { ConversationState } from "./conversation"
import { data, type BufferedEvent, type ChatEvent, type LocalEvent } from "./conversation/events"
import { SteerRejectedError, steerEvent, type SteerState } from "./conversation/steer"
import { turnEnded, turnFailed } from "./conversation/turn"
import type { ForkSessionPhase, ForkSessionPhaseDetail, SessionOrigin } from "./kiro-sessions.types"
import { watchMcpServerReady, type McpStatusListener } from "./mcp-ready"
import { SessionBusyError } from "./sessionErrors"
import type { LocalSessionNoticeCode } from "./sessionNotices"
import { AgentTimeoutError } from "./turnErrors"

export { DECK_ROOT }
export type { AcpModel }
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
const MAX_PROCESSES = 3
/** The engine every process runs on. */
const ENGINE: EngineId = "v2"
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
/** kiro-cli answers `_session/steer` and `_session/steer/clear` at once (it only queues). */
const STEER_TIMEOUT_MS = 10_000
/** Chat events kept for a reconnecting stream. */
const MAX_BUFFERED_EVENTS = 2000

type EventListener = (entry: BufferedEvent) => void

interface SpawnProcessOptions {
  setMode?: boolean
  onPhase?: (phase: ForkSessionPhase, detail?: ForkSessionPhaseDetail) => void
  signal?: AbortSignal
}

interface ProcessState {
  conn: AcpConnection
  engine: EngineId
  session: EngineSession
  /** What the engine advertised in its initialize answer (null until it answered). */
  caps: EngineCapabilities | null
  conversation: ConversationState
  /** The client id the process was created for (the fork's id for a fork); keys `pendingOrigins`. */
  clientId: string
  /** The deck this conversation last created. */
  deckId: string
  /** Decks whose `.session` this process wrote. */
  savedDecks: Set<string>
  sessionId: string | null
  agentName: string
  listeners: Set<EventListener>
  /** The setup's MCP readiness watches (mcp-ready.ts). */
  mcpListeners: Set<McpStatusListener>
  running: boolean
  /** A session/prompt request has been sent and has not been answered yet. */
  promptInFlight: boolean
  /** JSON-RPC id of the current turn's session/prompt; its response (result or error) ends the turn. */
  promptRequestId: number | null
  /** The current turn's chat events, numbered from 1. */
  buffer: BufferedEvent[]
  eventId: number
  lastActivity: number
  /** Turns ended so far; a steer whose turn ended while kiro-cli queued it is taken back. */
  turnsEnded: number
  /** A `_session/steer/clear` in flight; the next prompt waits for it. */
  steerClear: Promise<void> | null
  /** Stop was pressed during this turn: a turn that ends now is not continued with its steers. */
  stopRequested: boolean
}

/** Map keyed by sessionId; one process may sit under several keys (client id and kiro session id). */
const processes = new Map<string, ProcessState>()
export const pendingOrigins = new Map<string, SessionOrigin>()

// Model info (shared, populated from first process)
let currentModelId = ""
let availableModels: AcpModel[] = []

// ── Per-process helpers ──

/** Number a chat event, buffer it for /stream reconnects and hand it to every listener. */
function push(ps: ProcessState, event: ChatEvent): void {
  const entry: BufferedEvent = { id: ++ps.eventId, event }
  ps.buffer.push(entry)
  if (ps.buffer.length > MAX_BUFFERED_EVENTS) ps.buffer.shift()
  for (const fn of ps.listeners) fn(entry)
}

/** One kiro-cli notification: through the engine to the MCP watch and the conversation model. */
function handleNotification(ps: ProcessState, msg: Parameters<EngineSession["translate"]>[0]): void {
  const events = ps.session.translate(msg)
  if (!events.length) return
  const chat: LocalEvent[] = []
  for (const event of events) {
    if (event.type === "mcp_status") {
      for (const fn of [...ps.mcpListeners]) fn(event)
    } else if (event.type !== "mcp_snapshot") {
      chat.push(event)
    }
  }
  if (!chat.length) return
  const { events: out, deckId } = ps.conversation.apply(chat)
  if (deckId) saveDeck(ps, deckId)
  for (const event of out) push(ps, event)
}

/**
 * A tool result named a deck: write the session to its `.session` once, and the fork's origin to
 * the first deck the conversation creates.
 */
function saveDeck(ps: ProcessState, deckId: string): void {
  if (ps.savedDecks.has(deckId) || !ps.sessionId) return
  if (!saveSessionToDeck(deckId, ps.sessionId)) return
  ps.savedDecks.add(deckId)
  ps.deckId = deckId
  const origin = pendingOrigins.get(ps.clientId)
  if (origin) {
    saveOriginToDeck(deckId, origin)
    pendingOrigins.delete(ps.clientId)
  }
}

/** The turn started by sendPrompt is over: release the session and tell the listeners. */
function endTurn(ps: ProcessState, end: ChatEvent): void {
  ps.promptRequestId = null
  ps.promptInFlight = false
  ps.running = false
  ps.stopRequested = false
  ps.turnsEnded++
  ps.session.endTurn()
  discardSteers(ps)
  push(ps, end)
}

/** Tell the listeners (and a reconnecting stream) where a steer is now. */
function pushSteer(ps: ProcessState, steer: { id: string; text?: string; state: SteerState }): void {
  push(ps, steerEvent(steer))
}

/**
 * Take what kiro-cli still queues for this session out of its queue. Left there, V2 and V3 both
 * put it into the next prompt, after a Stop and (V2) after a normal end.
 */
function clearSteerQueue(ps: ProcessState): void {
  if (ps.conn.exited) return
  const cleared = ps.conn.request("_session/steer/clear", { sessionId: ps.sessionId }, { timeoutMs: STEER_TIMEOUT_MS })
    .then(() => undefined, (error: Error) => { console.warn("[acp] _session/steer/clear: %s", error.message) })
  const done = cleared.finally(() => { if (ps.steerClear === done) ps.steerClear = null })
  ps.steerClear = done
}

/** The turn ended before kiro-cli read these steers: clear them and mark them not delivered. */
function discardSteers(ps: ProcessState): void {
  const left = ps.conversation.steers.takeAll()
  if (!left.length) return
  clearSteerQueue(ps)
  for (const steer of left) pushSteer(ps, { id: steer.id, state: "discarded" })
}

/**
 * The prompt ended (end_turn) before kiro-cli read these steers. As in Cloud, they are not
 * dropped: they are taken out of kiro-cli's queue (left there, kiro-cli would put them into the
 * user's next message) and sent as a follow-up prompt on the same turn and stream. A steer queued
 * after the clear is read by kiro-cli in that prompt itself. A Stop or an exit meanwhile ends the
 * turn instead, and a clear that fails ends it with the steers discarded.
 */
async function continueWithSteers(ps: ProcessState): Promise<void> {
  ps.promptRequestId = null
  const taken = ps.conversation.steers.peek()
  let cleared = true
  try {
    await ps.conn.request("_session/steer/clear", { sessionId: ps.sessionId }, { timeoutMs: STEER_TIMEOUT_MS })
  } catch (error) {
    console.warn("[acp] _session/steer/clear: %s", error instanceof Error ? error.message : String(error))
    cleared = false
  }
  if (ps.conn.exited || !ps.running) return
  if (!cleared || ps.stopRequested) {
    endTurn(ps, turnEnded(cleared ? "cancelled" : "end_turn"))
    return
  }
  ps.conversation.steers.remove(taken)
  console.log("[acp] sessionId=%s: prompt ended before %d steer(s) were read; sending them as a follow-up prompt", ps.sessionId, taken.length)
  for (const steer of taken) pushSteer(ps, { id: steer.id, state: "delivered" })
  startPrompt(ps, taken.map((steer) => steer.text).join("\n\n"))
}

/** Send session/prompt for the session's turn; its answer ends the turn (promptAnswered). */
function startPrompt(ps: ProcessState, text: string): void {
  const { id, response } = ps.conn.startRequest("session/prompt", {
    sessionId: ps.sessionId,
    prompt: [{ type: "text", text }],
  }, { onAnswer: (answer) => { if (ps.promptRequestId === id) promptAnswered(ps, answer) } })
  ps.promptRequestId = id
  // promptAnswered (an answer) or the exit handler (no answer) ends the turn for the listeners.
  void response.catch(() => {})
}

/**
 * Only the answer to this turn's session/prompt ends the turn (kiro-cli sends no turn end for
 * sub-agent sessions); an error answer to any other request (set_config_option, a steer) rejects
 * that request alone. It is handled in line order, before the lines that follow it.
 */
function promptAnswered(ps: ProcessState, answer: AcpAnswer): void {
  if (!answer.ok) {
    endTurn(ps, turnFailed({ message: answer.error.message }))
    return
  }
  const stopReason = (answer.result as Partial<PromptResponse> | undefined)?.stopReason ?? "end_turn"
  if (stopReason === "end_turn" && ps.conversation.steers.size && !ps.stopRequested) void continueWithSteers(ps)
  else endTurn(ps, turnEnded(stopReason))
}

/** Reports a session/load's replay progress as the fork's `loading` phase, at most every 20 updates or 250 ms. */
function replayProgress(onPhase: SpawnProcessOptions["onPhase"]): (replayed: number, done: boolean) => void {
  let lastReported = 0
  let lastReportAt = Date.now()
  return (replayed, done) => {
    if (!onPhase) return
    const now = Date.now()
    if (done ? replayed !== lastReported : replayed % 20 === 0 || now - lastReportAt >= 250) {
      lastReported = replayed
      lastReportAt = now
      onPhase("loading", { replayed })
    }
  }
}

/**
 * Start kiro-cli and open a session in it: `existingSessionId` is restored with session/load,
 * otherwise a new session is created. `clientId` is the client the process is created for
 * (default: its kiro session id).
 */
async function spawnProcess(
  agentName: string,
  clientId: string | null,
  existingSessionId?: string,
  opts: SpawnProcessOptions = {},
): Promise<ProcessState> {
  if (opts.signal?.aborted) throw new DOMException("Fork cancelled", "AbortError")
  opts.onPhase?.("starting")
  // Re-derive .kiro/agents/ from the acp-agents catalog + user selection on
  // every spawn (idempotent, all-or-nothing) — a `git pull` that updates the
  // catalog takes effect on the next spawn. If the derivation fails, the
  // spawn fails: launching from silently stale agent files is the exact bug
  // this re-derivation exists to prevent.
  syncToAgentsDir()
  const cfg = getActiveAgent()
  const args = [...cfg.args]
  const flagIdx = args.indexOf("--agent")
  if (flagIdx >= 0 && flagIdx + 1 < args.length) {
    args[flagIdx + 1] = agentName
  }
  const conn = spawnAcp(cfg.path, args, {
    cwd: MCP_LOCAL_DIR,
    env: { ...process.env, ...cfg.env, SDPM_OUTPUT_DIR: DECK_ROOT, SDPM_DECK_ROOT: DECK_ROOT },
  })
  const abortSpawn = () => conn.kill()
  opts.signal?.addEventListener("abort", abortSpawn, { once: true })

  const engine = adapterFor(ENGINE)
  const mcpListeners = new Set<McpStatusListener>()
  const ps: ProcessState = {
    conn,
    engine: engine.id,
    session: engine.createSession({
      request: (method, params, requestOpts) => conn.request(method, params, requestOpts),
      cwd: MCP_LOCAL_DIR,
      setupTimeoutMs: SESSION_SETUP_TIMEOUT_MS,
      mcpReadyTimeoutMs: MCP_READY_TIMEOUT_MS,
      signal: opts.signal,
      watchMcp: (sessionId) => watchMcpServerReady(mcpListeners, sessionId),
    }),
    caps: null,
    conversation: new ConversationState(),
    clientId: clientId ?? "",
    deckId: "",
    savedDecks: new Set(),
    sessionId: null,
    agentName,
    listeners: new Set(),
    mcpListeners,
    running: false, promptInFlight: false, promptRequestId: null, buffer: [], eventId: 0,
    lastActivity: Date.now(), turnsEnded: 0, steerClear: null, stopRequested: false,
  }
  conn.onNotification((msg) => handleNotification(ps, msg))
  // The process is gone: end a running turn with an error the stream forwards (otherwise the
  // chat would spin forever), and drop it from the map. The transport has already failed what
  // waited on it.
  conn.onExit((code) => {
    console.log("[acp close] sessionId=%s code=%s", ps.sessionId, code)
    if (ps.promptInFlight) endTurn(ps, turnFailed({ code: "agent_exited", message: `kiro-cli exited with code ${code}` }))
    forgetProcess(ps)
  })

  try {
    const init = await conn.request("initialize", {
      protocolVersion: 1,
      clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
      clientInfo: { name: "sdpm-local", version: "0.1.0" },
    }, { timeoutMs: INITIALIZE_TIMEOUT_MS, signal: opts.signal }) as InitializeResponse
    ps.caps = engine.capabilities(init)

    if (existingSessionId) {
      // Restore existing session context (Obsidian agent-client pattern)
      const opened = await ps.session.openSession(existingSessionId, agentName, {
        setMode: opts.setMode,
        onReplay: replayProgress(opts.onPhase),
        onSwitching: () => opts.onPhase?.("switching"),
      })
      ps.sessionId = opened.sessionId
    } else {
      ps.sessionId = (await ps.session.newSession(agentName)).sessionId
    }
    if (!ps.clientId) ps.clientId = ps.sessionId

    // Extract model info from first process
    const models = availableModels.length ? null : ps.session.models()
    if (models) {
      currentModelId = models.current
      availableModels = models.available
        .filter(o => !o.description?.startsWith("[Internal]") && !o.description?.startsWith("[Deprecated]"))
    }

    opts.signal?.removeEventListener("abort", abortSpawn)
    return ps
  } catch (error) {
    opts.signal?.removeEventListener("abort", abortSpawn)
    conn.kill()
    throw error
  }
}

/** Remove every map key that refers to a process, and the origin a fork left for its first deck. */
function forgetProcess(ps: ProcessState): void {
  let registered = false
  for (const [key, candidate] of processes) {
    if (candidate === ps) {
      processes.delete(key)
      registered = true
    }
  }
  if (registered) pendingOrigins.delete(ps.clientId)
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
    oldest.conn.kill()
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
  ps.conn.kill()
}

/**
 * Get or create a process for a sessionId (the map key). With no live process, spawns one and
 * restores `kiroSessionId` (default: the key) with session/load; a live process already under
 * `kiroSessionId` is reused. Either way the process is then registered under both ids.
 */
export async function getOrCreateProcess(
  sessionId: string,
  agentName: string = "sdpm-orchestrator",
  opts: SpawnProcessOptions & { kiroSessionId?: string } = {},
): Promise<ProcessState> {
  const kiroSessionId = opts.kiroSessionId ?? sessionId
  let ps = processes.get(sessionId) ?? processes.get(kiroSessionId)
  if (ps) {
    processes.set(sessionId, ps)
    ps.lastActivity = Date.now()
    return ps
  }
  // No live process — spawn new one and restore session context
  await evictIfNeeded()
  ps = await spawnProcess(agentName, sessionId, kiroSessionId, opts)
  processes.set(sessionId, ps)
  processes.set(kiroSessionId, ps)
  return ps
}

/** Spawn a brand-new process (no existing session). Returns the new sessionId. */
export async function createNewProcess(agentName: string = "sdpm-orchestrator"): Promise<ProcessState> {
  await evictIfNeeded()
  const ps = await spawnProcess(agentName, null)
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
  const ps = await spawnProcess(agentName, clientSessionId, undefined, opts)
  processes.set(clientSessionId, ps)
  processes.set(ps.sessionId!, ps)
  return ps
}

/**
 * Send a prompt to a session's process. The turn's chat events are numbered from 1; a `notice`
 * about the turn's session (sessionNotices.ts) is the first of them.
 * Throws SessionBusyError while the process is still answering an earlier prompt
 * (the same session open in two panels or tabs); prompts are not queued.
 */
export async function sendPrompt(
  sessionId: string,
  text: string,
  agentName?: string,
  opts: { notice?: LocalSessionNoticeCode } = {},
): Promise<{ sessionId: string; subscribe: (fn: EventListener) => () => void; send: () => void }> {
  const ps = await getOrCreateProcess(sessionId, agentName || "sdpm-orchestrator")
  // Steers the last turn left must be out of kiro-cli's queue before this prompt.
  if (ps.steerClear) await ps.steerClear
  if (ps.promptInFlight) throw new SessionBusyError()
  ps.promptInFlight = true
  ps.running = true
  ps.stopRequested = false
  ps.session.beginTurn()
  ps.conversation.beginTurn()
  ps.buffer = []; ps.eventId = 0
  ps.lastActivity = Date.now()
  if (opts.notice) push(ps, data({ notice: { code: opts.notice } }))

  return {
    sessionId: ps.sessionId!,
    subscribe: (fn: EventListener) => {
      ps.listeners.add(fn)
      return () => { ps.listeners.delete(fn) }
    },
    send: () => startPrompt(ps, text),
  }
}

/**
 * Send a message into the session's running turn (`_session/steer`). Resolves once kiro-cli
 * queued it; the listeners then get its steer event `accepted`, later `delivered` or `discarded`.
 * Throws SteerRejectedError when no turn runs, kiro-cli does not queue it, or the turn ended
 * meanwhile (the message is then taken back out of kiro-cli's queue).
 */
export async function steerSession(sessionId: string, id: string, text: string): Promise<void> {
  const ps = processes.get(sessionId)
  if (!ps || !ps.promptInFlight) throw new SteerRejectedError("session_idle")
  const turn = ps.turnsEnded
  let result: { queued?: boolean; messageId?: string; dropped?: string } | undefined
  try {
    result = await ps.conn.request("_session/steer", { sessionId: ps.sessionId, message: text }, { timeoutMs: STEER_TIMEOUT_MS }) as typeof result
  } catch (error) {
    if (error instanceof AgentTimeoutError) throw error
    throw new SteerRejectedError("steer_not_queued", error instanceof Error ? error.message : String(error))
  }
  // V3 drops a steer that raced the end of the turn (`dropped: "epoch_changed"`).
  if (result?.queued !== true) throw new SteerRejectedError("steer_not_queued", result?.dropped)
  if (ps.turnsEnded !== turn) {
    clearSteerQueue(ps)
    throw new SteerRejectedError("session_idle")
  }
  ps.conversation.steers.add({ id, text, ...(result.messageId ? { messageId: result.messageId } : {}) })
  ps.lastActivity = Date.now()
  pushSteer(ps, { id, text, state: "accepted" })
}

/** Send session/cancel to every session the engine runs this turn on. */
function cancelTurn(ps: ProcessState): void {
  for (const target of ps.session.cancelTargets()) ps.conn.notify("session/cancel", { sessionId: target })
}

/** Cancel a session's active prompt. */
export function cancelSession(sessionId: string): void {
  const ps = processes.get(sessionId)
  if (!ps) return
  if (ps.running) ps.stopRequested = true
  if (ps.sessionId) cancelTurn(ps)
}

/** Cancel all processes (stop button with no specific session). */
export function cancelAll(): void {
  for (const ps of processes.values()) {
    if (ps.running && ps.sessionId) {
      ps.stopRequested = true
      cancelTurn(ps)
    }
  }
}

/** Check if a session has a running process. */
export function isSessionRunning(sessionId: string): boolean {
  return processes.get(sessionId)?.running ?? false
}

/** The current turn's buffered chat events, after `afterId` when given (a reconnect's Last-Event-ID). */
export function getBufferedEvents(sessionId: string, afterId?: number): BufferedEvent[] {
  const ps = processes.get(sessionId)
  if (!ps) return []
  if (afterId == null) return [...ps.buffer]
  return ps.buffer.filter(e => e.id > afterId)
}

/** Subscribe to a session's chat events. */
export function subscribeToSession(sessionId: string): { sessionId: string | null; subscribe: (fn: EventListener) => () => void } | null {
  const ps = processes.get(sessionId)
  if (!ps) return null
  return {
    sessionId: ps.sessionId,
    subscribe: (fn: EventListener) => {
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
  await ps.conn.request("session/set_config_option", { sessionId: ps.sessionId, configId, value })
}

/** Save sessionId to deck's .session file. Returns whether it was written (the deck exists). */
export function saveSessionToDeck(deckId: string, sessionId: string): boolean {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir || !fs.existsSync(dir)) return false
  fs.writeFileSync(path.join(dir, ".session"), sessionId, "utf-8")
  return true
}

/** The kiro session id saved in a deck's .session file, or null when the deck has none. */
export function readSessionFromDeck(deckId: string): string | null {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return null
  try { return fs.readFileSync(path.join(dir, ".session"), "utf-8").trim() || null } catch { return null }
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
    for (const ps of processes.values()) ps.conn.kill()
    processes.clear()
    pendingOrigins.clear()
  })
}
