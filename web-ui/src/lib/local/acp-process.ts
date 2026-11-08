// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Process Manager — manages multiple kiro-cli acp child processes, one conversation each.
 * Enables background processing: switching decks does not interrupt running agents.
 *
 * Each process is a transport connection (acp/transport.ts), the engine's session for it
 * (acp/engine.ts; the engine is read from acp-config.json at every start) and the chat's
 * conversation model (conversation/). Every kiro-cli notification goes through the engine's
 * `translate`: its MCP events to the process's MCP record (mcp-ready.ts), recorded from the start
 * so a setup wait never misses one, the rest to the conversation model, whose chat events are
 * numbered and buffered here (the SSE `id:`, the same for live and replayed events) and handed to
 * the listeners. A process enters the map only once its session runs the requested agent's mode
 * and its sdpm server is ready; a start that fails is killed and reported as AgentStartError,
 * AgentTimeoutError or SessionLockedError.
 *
 * Map keys (`register`, the only place that adds them): every client id that uses the process
 * and its current kiro session id (the one saved to the deck's `.session`), so a second tab or a
 * reopened deck reuses the live process instead of loading the session into a second kiro-cli,
 * which the first one still locks. An id the process does not hold (a saved id kiro-cli replaced)
 * is never a key.
 *
 * Decks: a deck a tool result names gets the session's `.session` (and a fork's origin) here,
 * whether or not a browser is listening; a reopened deck's process is bound to it. Next to
 * `.session`, `.session-engine` records the engines that ran the session's turns, so a deck
 * continued on the other engine says so (its turns there are in the other engine's copy). A
 * deck-bound process whose engine is no longer the configured one is ended once idle (Settings,
 * or the end of its turn), and the deck's next message opens `.session` on the new engine.
 *
 * Forks (`forkSession`): a new kiro-cli makes the fork with its engine (`EngineSession.forkSession`)
 * and opens it; a fork kiro-cli could not read, or a start that fails or is cancelled once the
 * fork exists, is deleted through that session (`discardFork`), never anything else.
 *
 * Listing the stored sessions (`withEngineConnection`) uses a live process of the engine, else a
 * short-lived kiro-cli that opens no session and is killed when the listing is done.
 *
 * Models: each chat chooses its kiro session's model and effort (`chooseSessionModel`). An idle
 * live process changes them at once (the engine's setModel, one change at a time); otherwise the
 * choice waits under the chat's client id and is applied right before its next session/prompt,
 * so a turn never switches models half-way. The models are listed without starting kiro-cli:
 * from the chat's live session, else the last list a session of the configured engine reported
 * (kept in acp-models.json, acp/model-cache.ts).
 *
 * Max MAX_PROCESSES concurrent processes. Idle processes are evicted LRU.
 */
import path from "path"
import { DECK_ROOT, resolveDeckDir } from "./deck-paths"
import { syncToAgentsDir } from "./agents-sync"
import {
  adapterFor, type EngineCapabilities, type EngineId, type EngineSession, type LoadOutcome, type ModelChoice, type ModelOption,
  type StoreContext,
} from "./acp/engine"
import { isEngineId, readEngineConfig } from "./acp/engine-config"
import { readModelCache, writeModelCache } from "./acp/model-cache"
import type { InitializeResponse, PromptResponse } from "./acp/schema"
import { AcpRequestError, METHOD_NOT_FOUND, spawnAcp, type AcpAnswer, type AcpConnection } from "./acp/transport"
import { ConversationState } from "./conversation"
import { data, type BufferedEvent, type ChatEvent, type LocalEvent } from "./conversation/events"
import { SteerRejectedError, steerEvent, type SteerState } from "./conversation/steer"
import { turnEnded, turnFailed } from "./conversation/turn"
import type { ForkSessionPhase, ForkSessionPhaseDetail, SessionOrigin } from "./kiro-sessions.types"
import { McpRecord, SDPM_MCP_SERVER, waitForMcp } from "./mcp-ready"
import { ForkNotReadError, ModelChoiceError, SessionBusyError, SessionLockedError } from "./sessionErrors"
import type { LocalSessionNoticeCode } from "./sessionNotices"
import { AgentStartError, AgentTimeoutError } from "./turnErrors"

export { DECK_ROOT }
export type { LoadOutcome, ModelChoice, ModelOption }
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
/** kiro-cli answers `_session/steer` and `_session/steer/clear` at once (it only queues). */
const STEER_TIMEOUT_MS = 10_000
/** Chat events kept for a reconnecting stream. */
const MAX_BUFFERED_EVENTS = 2000
const INITIALIZE_PARAMS = {
  protocolVersion: 1,
  clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
  clientInfo: { name: "sdpm-local", version: "0.1.0" },
}
/** The agent a listing kiro-cli is started with (V3 ignores it; V2's store is read without kiro-cli). */
const LISTING_AGENT = "sdpm-orchestrator"
/** What a deck's `.session` may hold: a kiro session id (V2 UUID, V3 `sess_<uuid>`). */
const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/
/** Model choices kept for chats without an idle process; the oldest is dropped beyond this. */
const MAX_PENDING_MODEL_CHOICES = 100

type EventListener = (entry: BufferedEvent) => void

interface SpawnOptions {
  /** Open this saved session instead of creating one. */
  open?: string
  /** Fork this stored session and open the fork instead of creating one. */
  fork?: string
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
  /** Every client id the process is registered under (`clientId` among them). */
  clientIds: Set<string>
  /** The deck this conversation last created or was opened for. */
  deckId: string
  /** Decks whose `.session` names this process's session. */
  savedDecks: Set<string>
  /** The process belongs to a deck: an engine switch ends it once it is idle. */
  deckBound: boolean
  /** Its sessions' MCP servers, recorded since kiro-cli started. */
  mcp: McpRecord
  sessionId: string | null
  agentName: string
  listeners: Set<EventListener>
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
  /** A model change in flight; the next change and the next prompt wait for it. */
  configChange: Promise<void> | null
}

/** Map keyed by client ids and kiro session ids (`register`). */
const processes = new Map<string, ProcessState>()
export const pendingOrigins = new Map<string, SessionOrigin>()

/** The model list a session of each engine last reported in this server (also in acp-models.json). */
const knownModels = new Map<EngineId, ModelOption[]>()
/** Client id → the model choice its chat made while no idle process could take it. */
const pendingModelChoices = new Map<string, ModelChoice>()

// ── Per-process helpers ──

/** Number a chat event, buffer it for /stream reconnects and hand it to every listener. */
function push(ps: ProcessState, event: ChatEvent): void {
  const entry: BufferedEvent = { id: ++ps.eventId, event }
  ps.buffer.push(entry)
  if (ps.buffer.length > MAX_BUFFERED_EVENTS) ps.buffer.shift()
  for (const fn of ps.listeners) fn(entry)
}

/** One kiro-cli notification: through the engine to the MCP record and the conversation model. */
function handleNotification(ps: ProcessState, msg: Parameters<EngineSession["translate"]>[0]): void {
  for (const event of adapterFor(ps.engine).translateMcp(msg)) {
    if (event.type === "mcp_status" || event.type === "mcp_snapshot") ps.mcp.apply(event)
  }
  const chat: LocalEvent[] = ps.session.translate(msg)
  if (!chat.length) return
  const { events: out, deckId } = ps.conversation.apply(chat)
  if (deckId) saveDeck(ps, deckId)
  for (const event of out) push(ps, event)
}

/**
 * A tool result named a deck: write the session to its `.session` once (and a new engine mark),
 * and the fork's origin to the first deck the conversation creates.
 */
function saveDeck(ps: ProcessState, deckId: string): void {
  if (ps.savedDecks.has(deckId) || !ps.sessionId) return
  if (!saveSessionToDeck(deckId, ps.sessionId)) return
  writeEngineMark(deckId, { last: ps.engine, engines: [ps.engine] })
  ps.savedDecks.add(deckId)
  ps.deckId = deckId
  ps.deckBound = true
  const origin = pendingOrigins.get(ps.clientId)
  if (origin) {
    saveOriginToDeck(deckId, origin)
    pendingOrigins.delete(ps.clientId)
  }
}

/** The turn started by sendPrompt is over: release the session, close what it left open (steers, a Compose card) and tell the listeners. */
function endTurn(ps: ProcessState, end: ChatEvent): void {
  ps.promptRequestId = null
  ps.promptInFlight = false
  ps.running = false
  ps.stopRequested = false
  ps.turnsEnded++
  ps.session.endTurn()
  discardSteers(ps)
  for (const event of ps.conversation.endTurn()) push(ps, event)
  push(ps, end)
  // Settings switched the engine while this turn ran: the deck's next message opens it on the new one.
  if (ps.deckBound && !ps.conn.exited && ps.engine !== readEngineConfig().engine) {
    console.log("[acp] sessionId=%s: the agent engine is no longer %s; ending the deck's process", ps.sessionId, ps.engine)
    forgetProcess(ps)
    ps.conn.kill()
  }
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
 * sub-agent sessions); an error answer to any other request (a steer, a model change) rejects
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
function replayProgress(onPhase: SpawnOptions["onPhase"]): (replayed: number, done: boolean) => void {
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

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** What a failed start is reported as. The process is killed either way. */
function startFailure(ps: ProcessState, error: unknown): unknown {
  if (error instanceof Error && error.name === "AbortError") return error
  if (error instanceof AgentTimeoutError) return error
  if (error instanceof AgentStartError) {
    console.warn("[acp] %s: %s", error.code, error.message)
    return error
  }
  const kind = ps.session.classifyError(error)
  if (kind === "session_locked") return new SessionLockedError(errorText(error))
  if (kind === "auth_required") {
    console.warn("[acp] agent_auth_required: %s", errorText(error))
    return new AgentStartError("agent_auth_required", errorText(error))
  }
  if (ps.conn.exited) {
    console.error("[acp] kiro-cli exited while starting (code %s): %s\n%s", ps.conn.exitCode, errorText(error), ps.conn.stderrTail().join("\n"))
    return new AgentStartError("agent_start_failed", `kiro-cli exited while starting (code ${ps.conn.exitCode}): ${errorText(error)}`)
  }
  return error
}

/**
 * Start kiro-cli on the configured engine and open a session in it: `opts.open` is restored with
 * the engine's openSession, otherwise a new session is created. `clientId` is the client the
 * process is created for (default: its kiro session id). The process is not registered yet.
 */
async function spawnProcess(agentName: string, clientId: string | null, opts: SpawnOptions = {}): Promise<{ ps: ProcessState; outcome: LoadOutcome }> {
  if (opts.signal?.aborted) throw new DOMException("Request cancelled", "AbortError")
  opts.onPhase?.("starting")
  const config = readEngineConfig()
  const engine = adapterFor(config.engine)
  // Re-derive .kiro/agents/ from the acp-agents catalog + user selection on
  // every spawn (idempotent, all-or-nothing) — a `git pull` that updates the
  // catalog takes effect on the next spawn. If the derivation fails, the
  // spawn fails: launching from silently stale agent files is the exact bug
  // this re-derivation exists to prevent.
  // An engine whose sub-agents follow the session's model gets no model in the composer's
  // definition, so the composer runs on the chat's choice.
  try {
    syncToAgentsDir(undefined, undefined, { pinSubagentModel: !engine.subagentsFollowSessionModel })
  } catch (error) {
    console.error("[acp] agent definitions: %s", errorText(error))
    throw new AgentStartError("agent_start_failed", `agent definitions: ${errorText(error)}`)
  }
  const env = { ...process.env, ...config.env, SDPM_OUTPUT_DIR: DECK_ROOT, SDPM_DECK_ROOT: DECK_ROOT }
  const conn = spawnAcp(config.command, [...config.commandArgs, ...engine.spawnArgs(agentName)], { cwd: MCP_LOCAL_DIR, env })
  /** The fork this start made (`opts.fork`), deleted again if the start fails. */
  let forkId: string | null = null
  // Once a fork exists, a cancel fails the pending request (its signal) and the catch below
  // deletes the fork before the kill; until then the kill is the quickest way out.
  const abortSpawn = () => { if (!forkId) conn.kill() }
  opts.signal?.addEventListener("abort", abortSpawn, { once: true })

  const mcp = new McpRecord()
  const ps: ProcessState = {
    conn,
    engine: engine.id,
    session: engine.createSession({
      request: (method, params, requestOpts) => conn.request(method, params, requestOpts),
      cwd: MCP_LOCAL_DIR,
      env,
      setupTimeoutMs: SESSION_SETUP_TIMEOUT_MS,
      signal: opts.signal,
      hostAgent: agentName,
      waitForMcp: async (sessionId) => {
        if (!(await waitForMcp(mcp, sessionId, SDPM_MCP_SERVER, MCP_READY_TIMEOUT_MS, opts.signal))) {
          console.warn("[acp] sdpm MCP server not connected after %dms (session %s); going on", MCP_READY_TIMEOUT_MS, sessionId)
        }
      },
      clearMcp: (sessionId) => mcp.clear(sessionId),
    }),
    caps: null,
    conversation: new ConversationState(),
    clientId: clientId ?? "",
    clientIds: new Set(),
    deckId: "",
    savedDecks: new Set(),
    deckBound: false,
    mcp,
    sessionId: null,
    agentName,
    listeners: new Set(),
    running: false, promptInFlight: false, promptRequestId: null, buffer: [], eventId: 0,
    lastActivity: Date.now(), turnsEnded: 0, steerClear: null, stopRequested: false, configChange: null,
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
    const init = await conn.request("initialize", INITIALIZE_PARAMS, { timeoutMs: INITIALIZE_TIMEOUT_MS, signal: opts.signal }) as InitializeResponse
    ps.caps = engine.capabilities(init)

    let outcome: LoadOutcome = "created"
    if (opts.fork) {
      const forked = await ps.session.forkSession(opts.fork, agentName, {
        onCopying: () => opts.onPhase?.("copying"),
        onForked: (id) => { forkId = id },
        onReplay: replayProgress(opts.onPhase),
        onSwitching: () => opts.onPhase?.("switching"),
      })
      ps.sessionId = forked.sessionId
      outcome = forked.outcome
    } else if (opts.open) {
      // Restore existing session context (Obsidian agent-client pattern)
      const opened = await ps.session.openSession(opts.open, agentName, {
        onReplay: replayProgress(opts.onPhase),
        onSwitching: () => opts.onPhase?.("switching"),
      })
      ps.sessionId = opened.sessionId
      outcome = opened.outcome
    } else {
      ps.sessionId = (await ps.session.newSession(agentName)).sessionId
    }
    if (!ps.clientId) ps.clientId = ps.sessionId

    rememberModels(ps)

    opts.signal?.removeEventListener("abort", abortSpawn)
    return { ps, outcome }
  } catch (error) {
    opts.signal?.removeEventListener("abort", abortSpawn)
    const failure = startFailure(ps, error)
    if (forkId) await discardFork(ps, forkId)
    conn.kill()
    throw failure
  }
}

/** Delete a fork through the session that made it; a failure is logged (the fork stays behind). */
async function discardFork(ps: ProcessState, forkId: string): Promise<void> {
  try {
    await ps.session.discardFork(forkId)
    console.log("[acp] removed the fork %s", forkId)
  } catch (error) {
    console.warn("[acp] could not remove the fork %s: %s", forkId, errorText(error))
  }
}

/**
 * Run `fn` with a lazy connection to an initialized kiro-cli of `engine`: a live registered
 * process of that engine, else a short-lived one (the configured command, cwd servers/local, no
 * session), started on the first `connect` and killed once `fn` is done. A short-lived one is
 * never registered. Concurrent listings are shared by the session catalog, not here.
 */
export async function withEngineConnection<T>(engine: EngineId, fn: (connect: StoreContext["connect"]) => Promise<T>): Promise<T> {
  const listing: { spawned?: Promise<{ conn: AcpConnection; caps: EngineCapabilities }> } = {}
  const connect: StoreContext["connect"] = async () => {
    const live = Array.from(new Set(processes.values())).find((ps) => ps.engine === engine && ps.caps && !ps.conn.exited)
    if (live) return { request: (method, params, requestOpts) => live.conn.request(method, params, requestOpts), caps: live.caps! }
    listing.spawned ??= startListingConnection(engine)
    const { conn, caps } = await listing.spawned
    return { request: (method, params, requestOpts) => conn.request(method, params, requestOpts), caps }
  }
  try {
    return await fn(connect)
  } finally {
    void listing.spawned?.then(({ conn }) => conn.kill(), () => {})
  }
}

/** A kiro-cli of `engine` that only answered initialize (it is killed by the caller, or here when initialize fails). */
async function startListingConnection(engine: EngineId): Promise<{ conn: AcpConnection; caps: EngineCapabilities }> {
  const config = readEngineConfig()
  const adapter = adapterFor(engine)
  const conn = spawnAcp(config.command, [...config.commandArgs, ...adapter.spawnArgs(LISTING_AGENT)], {
    cwd: MCP_LOCAL_DIR, env: { ...process.env, ...config.env },
  })
  try {
    const init = await conn.request("initialize", INITIALIZE_PARAMS, { timeoutMs: INITIALIZE_TIMEOUT_MS }) as InitializeResponse
    console.log("[acp] started a %s kiro-cli (pid %s) to list its sessions", engine, conn.pid)
    return { conn, caps: adapter.capabilities(init) }
  } catch (error) {
    conn.kill()
    throw error
  }
}

/** The only way into the map: the process under every client id that uses it and its kiro session id. */
function register(ps: ProcessState, clientId: string): void {
  ps.clientIds.add(clientId)
  for (const id of ps.clientIds) processes.set(id, ps)
  processes.set(ps.sessionId!, ps)
  ps.lastActivity = Date.now()
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

/** The live process of a client id or of the kiro session id it opens, registered under the client id. */
function findLive(clientId: string, sessionId: string | null): ProcessState | null {
  const ps = processes.get(clientId) ?? (sessionId ? processes.get(sessionId) : undefined)
  if (!ps) return null
  register(ps, clientId)
  return ps
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

/** End every idle deck-bound process that runs another engine than `engine` (a Settings switch). */
export function terminateIdleProcesses(engine: EngineId): void {
  for (const ps of new Set(processes.values())) {
    if (ps.promptInFlight || !ps.deckBound || ps.engine === engine) continue
    console.log("[acp] sessionId=%s: the agent engine is now %s; ending the deck's %s process", ps.sessionId, engine, ps.engine)
    forgetProcess(ps)
    ps.conn.kill()
  }
}

/** What the engine of a session's process advertised (null without a process). For phase 3. */
export function getCapabilities(sessionId: string): EngineCapabilities | null {
  return processes.get(sessionId)?.caps ?? null
}

/** Spawn a new process for a new chat and register it under the client's id and its kiro session id. */
export async function createNewProcessFor(
  clientId: string,
  agentName: string = "sdpm-orchestrator",
  opts: { signal?: AbortSignal } = {},
): Promise<ProcessState> {
  await evictIfNeeded()
  const { ps } = await spawnProcess(agentName, clientId, opts)
  register(ps, clientId)
  return ps
}

/**
 * The process of a reopened deck, registered under `clientId`: the live process of the client or
 * of the deck's saved session (`resumed`), else a new kiro-cli that opens the saved session (its
 * engine tells `resumed` from `created`), or creates one when the deck has none (`created`). The
 * process is bound to the deck either way. A created session is saved to `.session` with a new
 * engine mark; a resumed one reports `otherEngine` when its turns also ran on the other engine.
 */
export async function openDeckSession(
  clientId: string,
  deckId: string,
  savedSessionId: string | null,
  agentName: string,
  opts: { signal?: AbortSignal } = {},
): Promise<{ ps: ProcessState; outcome: LoadOutcome; otherEngine: boolean }> {
  let ps = findLive(clientId, savedSessionId)
  let outcome: LoadOutcome = "resumed"
  if (!ps) {
    await evictIfNeeded()
    const spawned = await spawnProcess(agentName, clientId, { ...opts, ...(savedSessionId ? { open: savedSessionId } : {}) })
    ps = spawned.ps
    outcome = spawned.outcome
    register(ps, clientId)
  }
  ps.deckId = deckId
  ps.savedDecks.add(deckId)
  ps.deckBound = true
  if (outcome === "created") {
    saveSessionToDeck(deckId, ps.sessionId!)
    writeEngineMark(deckId, { last: ps.engine, engines: [ps.engine] })
    return { ps, outcome, otherEngine: false }
  }
  const mark = readEngineMark(deckId)
  return { ps, outcome, otherEngine: mark.last !== ps.engine && mark.engines.includes(ps.engine) }
}

/**
 * Fork a stored session (`sourceId`, any store the configured engine can open) in a new
 * kiro-cli and open the fork, registered under the fork's id (its client id too, which keys
 * `pendingOrigins`). A fork kiro-cli could not read is deleted again: ForkNotReadError.
 */
export async function forkSession(
  sourceId: string,
  agentName: string,
  opts: { signal?: AbortSignal; onPhase?: SpawnOptions["onPhase"] } = {},
): Promise<{ ps: ProcessState; sessionId: string; outcome: LoadOutcome }> {
  await evictIfNeeded()
  const { ps, outcome } = await spawnProcess(agentName, null, { ...opts, fork: sourceId })
  const sessionId = ps.sessionId!
  if (outcome === "created") {
    console.warn("[acp] fork %s of %s: kiro-cli could not read it", sessionId, sourceId)
    await discardFork(ps, sessionId)
    ps.conn.kill()
    throw new ForkNotReadError()
  }
  register(ps, sessionId)
  return { ps, sessionId, outcome }
}

/** Delete a fork `forkSession` made and end its process (a fork that is not live is left alone). */
export async function discardForkedSession(sessionId: string): Promise<void> {
  const ps = processes.get(sessionId)
  if (!ps || ps.sessionId !== sessionId) return
  forgetProcess(ps)
  await discardFork(ps, sessionId)
  ps.conn.kill()
}

/**
 * The process of a forked chat: `clientId` is the fork's id, which is also the forked kiro
 * session's. The live process, or a new kiro-cli that opens the fork (`created` when kiro-cli
 * could not read it and started an empty session).
 */
export async function openForkedSession(
  clientId: string,
  agentName: string,
  opts: { signal?: AbortSignal; onPhase?: SpawnOptions["onPhase"] } = {},
): Promise<{ ps: ProcessState; outcome: LoadOutcome }> {
  const live = findLive(clientId, null)
  if (live) return { ps: live, outcome: "resumed" }
  await evictIfNeeded()
  const { ps, outcome } = await spawnProcess(agentName, clientId, { ...opts, open: clientId })
  register(ps, clientId)
  return { ps, outcome }
}

/**
 * Send a prompt to a session's process. The turn's chat events are numbered from 1; a `notice`
 * about the turn's session (sessionNotices.ts) is the first of them. The chat's pending model
 * choice is applied first; one kiro-cli refuses is logged and the prompt goes on.
 * Throws SessionBusyError while the process is still answering an earlier prompt
 * (the same session open in two panels or tabs); prompts are not queued.
 */
export async function sendPrompt(
  sessionId: string,
  text: string,
  opts: { notice?: LocalSessionNoticeCode } = {},
): Promise<{ sessionId: string; subscribe: (fn: EventListener) => () => void; send: () => void }> {
  const ps = processes.get(sessionId)
  if (!ps) throw new Error(`no kiro-cli process for session ${sessionId}`)
  // Steers the last turn left must be out of kiro-cli's queue before this prompt.
  if (ps.steerClear) await ps.steerClear
  if (ps.promptInFlight) throw new SessionBusyError()
  ps.promptInFlight = true
  // The chat's model choice goes in before the prompt (a change made while idle has finished).
  if (ps.configChange) await ps.configChange
  const choice = pendingModelChoices.get(sessionId)
  if (choice) {
    pendingModelChoices.delete(sessionId)
    try {
      await applyModelChoice(ps, choice)
    } catch (error) {
      console.warn("[acp] sessionId=%s: could not apply the chat's model choice: %s", ps.sessionId, errorText(error))
    }
  }
  ps.running = true
  ps.stopRequested = false
  ps.session.beginTurn()
  ps.conversation.beginTurn()
  ps.buffer = []; ps.eventId = 0
  ps.lastActivity = Date.now()
  if (ps.deckBound) {
    for (const deckId of ps.savedDecks) {
      const mark = readEngineMark(deckId)
      writeEngineMark(deckId, { last: ps.engine, engines: mark.engines.includes(ps.engine) ? mark.engines : [...mark.engines, ps.engine] })
    }
  }
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
 * Throws SteerRejectedError when no turn runs, kiro-cli does not queue it (or does not implement
 * steering: then no later steer is sent to that process), or the turn ended meanwhile (the
 * message is then taken back out of kiro-cli's queue).
 */
export async function steerSession(sessionId: string, id: string, text: string): Promise<void> {
  const ps = processes.get(sessionId)
  if (!ps || !ps.promptInFlight) throw new SteerRejectedError("session_idle")
  if (ps.caps && !ps.caps.steer) throw new SteerRejectedError("steer_not_queued", "kiro-cli does not support steering")
  const turn = ps.turnsEnded
  let result: { queued?: boolean; messageId?: string; dropped?: string } | undefined
  try {
    result = await ps.conn.request("_session/steer", { sessionId: ps.sessionId, message: text }, { timeoutMs: STEER_TIMEOUT_MS }) as typeof result
  } catch (error) {
    if (error instanceof AgentTimeoutError) throw error
    if (error instanceof AcpRequestError && error.code === METHOD_NOT_FOUND && ps.caps) {
      ps.caps.steer = false
      console.warn("[acp] sessionId=%s: kiro-cli does not implement _session/steer; messages sent during a turn are refused", ps.sessionId)
    }
    throw new SteerRejectedError("steer_not_queued", errorText(error))
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

// ── Models ──

/** Keep the engine's model list when a session reported a new one (in memory and acp-models.json). */
function rememberModels(ps: ProcessState): void {
  const available = ps.session.models()?.available
  if (!available?.length) return
  const known = knownModels.get(ps.engine) ?? readModelCache(ps.engine)
  knownModels.set(ps.engine, available)
  if (JSON.stringify(known) !== JSON.stringify(available)) writeModelCache(ps.engine, available)
}

/** Change the session's model and effort, after any change still in flight; rejects with kiro-cli's error. */
function applyModelChoice(ps: ProcessState, choice: ModelChoice): Promise<void> {
  const previous = ps.configChange ?? Promise.resolve()
  const run = previous.then(() => ps.session.setModel(choice))
  const settled = run.then(() => {
    rememberModels(ps)
    console.log("[acp] sessionId=%s: model %s effort %s", ps.sessionId, choice.model ?? "(unchanged)", choice.effort ?? "(default)")
  }, () => {})
  ps.configChange = settled
  void settled.then(() => { if (ps.configChange === settled) ps.configChange = null })
  return run
}

/** A chat's models as the picker shows them. */
export interface LocalSessionModels {
  engine: EngineId
  available: ModelOption[]
  /** What the chat's live session runs (null without a live session that reported it). */
  current: { model: string; effort: string | null; effortLevels: string[] } | null
  /** A choice that applies from the chat's next message. */
  pending: ModelChoice | null
}

/**
 * The models of a chat (`clientId`): its live session's list and current model and effort, else
 * the configured engine's last known list (never a new kiro-cli). `pending` is the chat's choice
 * still to apply.
 */
export function getSessionModels(clientId?: string): LocalSessionModels {
  const pending = (clientId && pendingModelChoices.get(clientId)) || null
  const ps = clientId ? processes.get(clientId) : undefined
  const live = ps && !ps.conn.exited ? ps.session.models() : null
  if (ps && live) {
    return {
      engine: ps.engine,
      available: live.available,
      current: { model: live.current, effort: live.effort?.current ?? null, effortLevels: live.effort?.levels ?? [] },
      pending,
    }
  }
  const engine = readEngineConfig().engine
  return { engine, available: knownModels.get(engine) ?? readModelCache(engine), current: null, pending }
}

function keepPendingChoice(clientId: string, choice: ModelChoice): void {
  pendingModelChoices.delete(clientId)
  pendingModelChoices.set(clientId, choice)
  if (pendingModelChoices.size > MAX_PENDING_MODEL_CHOICES) pendingModelChoices.delete(pendingModelChoices.keys().next().value!)
}

/**
 * A chat chose a model and/or effort. Checked against the models it is offered (kiro-cli would
 * take any value): a known model; an effort only for a model with effort levels, one of them.
 * Applied at once when the chat's process is live and idle (ModelChoiceError `model_not_changed`
 * when kiro-cli refuses, and nothing is kept); otherwise kept for the chat's next message, where
 * a new model drops an effort chosen for the previous one. Answers the chat's models after it.
 */
export async function chooseSessionModel(clientId: string, choice: ModelChoice): Promise<LocalSessionModels> {
  const view = getSessionModels(clientId)
  if (!view.available.length) throw new ModelChoiceError("models_unknown")
  if (choice.model && !view.available.some((model) => model.modelId === choice.model)) throw new ModelChoiceError("unknown_model")
  const pending = view.pending
  if (choice.effort) {
    const target = choice.model ?? pending?.model ?? view.current?.model
    const levels = target && target === view.current?.model
      ? view.current.effortLevels
      : view.available.find((model) => model.modelId === target)?.effortLevels ?? []
    if (!levels.length) throw new ModelChoiceError("effort_not_supported")
    if (!levels.includes(choice.effort)) throw new ModelChoiceError("unknown_effort")
  }
  const merged: ModelChoice = choice.model && choice.model !== pending?.model
    ? { model: choice.model, ...(choice.effort ? { effort: choice.effort } : {}) }
    : { ...pending, ...choice }

  const ps = processes.get(clientId)
  if (ps && !ps.conn.exited && !ps.promptInFlight && ps.session.models()) {
    try {
      await applyModelChoice(ps, merged)
    } catch (error) {
      throw new ModelChoiceError("model_not_changed", errorText(error))
    }
    pendingModelChoices.delete(clientId)
  } else {
    keepPendingChoice(clientId, merged)
  }
  return getSessionModels(clientId)
}

// ── Deck files ──

/** Save sessionId to deck's .session file. Returns whether it was written (the deck exists). */
export function saveSessionToDeck(deckId: string, sessionId: string): boolean {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir || !fs.existsSync(dir)) return false
  fs.writeFileSync(path.join(dir, ".session"), sessionId, "utf-8")
  return true
}

/** The kiro session id saved in a deck's .session file, or null when the deck has none (or not a valid id). */
export function readSessionFromDeck(deckId: string): string | null {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return null
  let saved: string
  try { saved = fs.readFileSync(path.join(dir, ".session"), "utf-8").trim() } catch { return null }
  if (!saved) return null
  if (!SESSION_ID_PATTERN.test(saved)) {
    console.warn("[acp] deck %s: .session does not hold a kiro session id; treating the deck as having none", deckId)
    return null
  }
  return saved
}

/** The engines that ran turns of the session a deck's `.session` names (`.session-engine`). */
export interface EngineMark {
  /** The engine that started the session's last turn. */
  last: EngineId
  /** Every engine that started a turn of it. */
  engines: EngineId[]
}

/** A deck from before the mark existed: every session then ran on V2. */
const UNMARKED: EngineMark = { last: "v2", engines: ["v2"] }
const ENGINE_MARK_FILE = ".session-engine"
const brokenMarksWarned = new Set<string>()

/** A deck's engine mark; a deck without one (or with a broken one, warned once) counts as V2 only. */
export function readEngineMark(deckId: string): EngineMark {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return UNMARKED
  let text: string
  try { text = fs.readFileSync(path.join(dir, ENGINE_MARK_FILE), "utf-8") } catch { return UNMARKED }
  try {
    const raw = JSON.parse(text) as { version?: unknown; last?: unknown; engines?: unknown }
    if (raw?.version === 1 && isEngineId(raw.last) && Array.isArray(raw.engines) && raw.engines.length && raw.engines.every(isEngineId)) {
      return { last: raw.last, engines: [...new Set(raw.engines as EngineId[])] }
    }
  } catch { /* reported below */ }
  if (!brokenMarksWarned.has(deckId)) {
    brokenMarksWarned.add(deckId)
    console.warn("[acp] deck %s: %s is not readable; treating the deck as unmarked", deckId, ENGINE_MARK_FILE)
  }
  return UNMARKED
}

/** Replace a deck's engine mark (temp file + rename). A failure is logged: only a later notice is lost. */
export function writeEngineMark(deckId: string, mark: EngineMark): void {
  const fs = require("fs") as typeof import("fs")
  const dir = resolveDeckDir(deckId)
  if (!dir) return
  const file = path.join(dir, ENGINE_MARK_FILE)
  const tmp = `${file}.tmp-${process.pid}`
  try {
    fs.writeFileSync(tmp, JSON.stringify({ version: 1, last: mark.last, engines: mark.engines }), "utf-8")
    fs.renameSync(tmp, file)
  } catch (error) {
    console.warn("[acp] deck %s: could not write %s: %s", deckId, ENGINE_MARK_FILE, errorText(error))
    try { fs.rmSync(tmp, { force: true }) } catch { /* nothing to clean */ }
  }
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
