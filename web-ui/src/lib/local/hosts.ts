// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Host pool: the kiro-cli processes of the Local server. A *host* is one kiro-cli (one transport
 * connection, acp/transport.ts); a *host session* is one kiro session on it, read and written
 * through its engine's `EngineSession` (acp/engine.ts). Hosts know the chats that use their
 * sessions only as `SessionSink`s (chat.ts implements one; web-2's compose runs another).
 *
 * - One session per kiro-cli. kiro-cli's V3 agent server runs one sdpm turn at a time per process
 *   (the turns of other sessions wait in its queue: KAS 0.66.70 `agent-controller`, measured in the
 *   lane Y E2E), so every chat and every composer gets a kiro-cli of its own, on V3 as on V2; a
 *   second open on a host throws.
 * - Placement (`acquireForChat`): at most MAX_CHAT_HOSTS kiro-cli processes carry a chat; a new one
 *   releases the least recently active one whose chat is idle. A busy sink is never released here:
 *   when every candidate is busy, the cap is exceeded with a warning.
 * - Every kiro-cli is started by `spawnHost`: the agent definitions are synced first
 *   (agents-sync, which leaves an unchanged directory alone), the chat environment (deck root
 *   included), initialize.
 * - A start its chat gave up (its abort signal) is killed, and so is the kiro-cli of an open that
 *   failed or was given up (after deleting a fork it made). A kiro-cli that exits while its session
 *   waits for the sdpm server fails the open at once.
 * - Routing: each line goes once through the adapter's `translateMcp` into the host's MCP record
 *   (mcp-ready.ts, keyed by session id, so a line from before any session knew its id counts),
 *   then to the host session's `translate`, whose events go to its sink.
 * - Listings (`acquireForListing`) use a live chat's kiro-cli of the engine; without one they start
 *   one, killed once the listing is done.
 * - Composers (`acquireForComposer`): a kiro-cli of its own per compose group, started for
 *   `sdpm-composer` in a process group of its own and without `SDPM_LOCAL_COMPOSE` (chat and listing
 *   kiro-cli get `SDPM_LOCAL_COMPOSE=1`, so only an orchestrator's sdpm server lists compose_slides and
 *   message_composer). At most MAX_COMPOSER_HOSTS live in the server; further starts wait in order.
 *   A composer's slot is held until its whole process tree is gone, not only its kiro-cli.
 * - Ending a kiro-cli (`end`, `kill`): its process tree (acp/process-tree.ts: every process group of
 *   its descendants, V3's agent server and V2's MCP servers included) gets the signal; a tree not
 *   gone COMPOSER_GONE_TIMEOUT_MS after SIGTERM gets SIGKILL. `killAll` (the Local server ends)
 *   signals every tree synchronously from one process table.
 */
import path from "path"
import { syncToAgentsDir } from "./agents-sync"
import {
  adapterFor, type EngineAdapter, type EngineCapabilities, type EngineId, type EngineSession, type LoadOutcome, type SessionContext,
} from "./acp/engine"
import { readEngineConfig } from "./acp/engine-config"
import { defaultProcessDeps, ProcessTree, type ProcessDeps, type ProcRow } from "./acp/process-tree"
import type { InitializeResponse } from "./acp/schema"
import { AcpRequestError, METHOD_NOT_FOUND, spawnAcp, type AcpAnswer, type AcpConnection } from "./acp/transport"
import type { LocalEvent } from "./conversation/events"
import { DECK_ROOT } from "./deck-paths"
import type { ForkSessionPhase, ForkSessionPhaseDetail } from "./kiro-sessions.types"
import { McpRecord, SDPM_MCP_SERVER, waitForMcp } from "./mcp-ready"
import { AgentStartError, AgentTimeoutError } from "./turnErrors"

export const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
/** Matches the sdpm server's `timeout` in the ACP agent definitions. */
export const MCP_READY_TIMEOUT_MS = 120_000
/**
 * Setup requests that must not hang an invoke forever. session/new and session/load can wait
 * for the agent's MCP servers (their own timeout is MCP_READY_TIMEOUT_MS) and session/load
 * replays the whole history first, so they get that plus a margin. session/prompt has none:
 * a turn lasts as long as the agent works, and Stop ends it.
 */
export const INITIALIZE_TIMEOUT_MS = 30_000
export const SESSION_SETUP_TIMEOUT_MS = MCP_READY_TIMEOUT_MS + 60_000
/** kiro-cli answers `_session/steer` and `_session/steer/clear` at once (it only queues). */
export const STEER_TIMEOUT_MS = 10_000
export const INITIALIZE_PARAMS = {
  protocolVersion: 1,
  clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
  clientInfo: { name: "sdpm-local", version: "0.1.0" },
}
/** The agent a listing kiro-cli is started with (V3 ignores it; V2's store is read without kiro-cli). */
export const LISTING_AGENT = "sdpm-orchestrator"
/** kiro-cli processes with a chat alive at once; a new one releases the least recently active idle one. */
export const MAX_CHAT_HOSTS = 3
/** Composer kiro-cli processes (their whole trees) alive at once in the server; further starts wait in order. */
export const MAX_COMPOSER_HOSTS = 4
/** A tree not gone this long after SIGTERM gets SIGKILL; a composer's slot is freed this long after SIGKILL at the latest. */
export const COMPOSER_GONE_TIMEOUT_MS = 2000
/** How often an ending tree is asked whether it is gone. */
const GONE_POLL_MS = 100
/** The agent a composer kiro-cli is started for. */
export const COMPOSER_AGENT = "sdpm-composer"
/** The environment key that makes the sdpm server list compose_slides and message_composer. */
const LOCAL_COMPOSE_ENV = "SDPM_LOCAL_COMPOSE"

/** What uses a host session: a chat (chat.ts) or a compose run's composer session (`aux`, compose-run.ts). */
export interface SessionSink {
  readonly kind: "chat" | "aux"
  /** The session's events (never MCP state). */
  onEvents(events: LocalEvent[]): void
  /** The kiro-cli exited; every request still waiting has failed. */
  onHostExit(code: number | null): void
  /** A turn runs or work is held: never released by the pool. */
  busy(): boolean
  lastActivity(): number
  /** Give the session up (the pool needs its place). */
  release(): void | Promise<void>
}

/** How a session is opened: created, loaded from the store, or forked from a stored one. */
export type Open = { kind: "new" } | { kind: "load"; sessionId: string } | { kind: "fork"; sourceId: string }

export type OpenPhase = (phase: ForkSessionPhase, detail?: ForkSessionPhaseDetail) => void

/** An open kiro-cli refused for a reason the caller reports in its own terms (`session_locked`: an external V2 lock). */
export class HostOpenError extends Error {
  constructor(readonly kind: "session_locked", message: string) {
    super(message)
    this.name = "HostOpenError"
  }
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))
const abortError = () => new DOMException("Request cancelled", "AbortError")
const isAbort = (error: unknown) => error instanceof Error && error.name === "AbortError"

/** Reports a session/load's replay progress as the `loading` phase, at most every 20 updates or 250 ms. */
function replayProgress(onPhase: OpenPhase | undefined): (replayed: number, done: boolean) => void {
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

/** One kiro session on a host. */
export class HostSession {
  /** The kiro session id prompts go to (null until it is open). */
  sessionId: string | null = null

  constructor(readonly host: Host, readonly engine: EngineSession, public sink: SessionSink) {}

  /** Send session/prompt; `onAnswer` runs in line order (the transport's onAnswer). Returns the request id. */
  prompt(text: string, onAnswer: (answer: AcpAnswer) => void): number {
    const { id, response } = this.host.conn.startRequest("session/prompt", {
      sessionId: this.sessionId,
      prompt: [{ type: "text", text }],
    }, { onAnswer })
    this.host.lastActivity = Date.now()
    // onAnswer (an answer) or the sink's onHostExit (no answer) ends what the prompt started.
    void response.catch(() => {})
    return id
  }

  /**
   * `_session/steer`. A kiro-cli that answers Method not found gets no further steers (one
   * warning per host) and the answer is `{queued: false, dropped: "not_implemented"}`; a timeout
   * is rethrown; any other error rejects.
   */
  async steer(text: string): Promise<{ queued?: boolean; messageId?: string; dropped?: string }> {
    const caps = this.host.caps
    if (caps && !caps.steer) return { queued: false, dropped: "not_implemented" }
    try {
      const answer = await this.host.conn.request("_session/steer", { sessionId: this.sessionId, message: text }, { timeoutMs: STEER_TIMEOUT_MS })
      return (answer ?? {}) as { queued?: boolean; messageId?: string; dropped?: string }
    } catch (error) {
      if (error instanceof AgentTimeoutError) throw error
      if (error instanceof AcpRequestError && error.code === METHOD_NOT_FOUND && caps) {
        if (caps.steer) console.warn("[acp] sessionId=%s: kiro-cli does not implement _session/steer; messages sent during a turn are refused", this.sessionId)
        caps.steer = false
        return { queued: false, dropped: "not_implemented" }
      }
      throw error
    }
  }

  /** `_session/steer/clear`: take what kiro-cli still queues for this session out of its queue. */
  async clearSteers(): Promise<void> {
    await this.host.conn.request("_session/steer/clear", { sessionId: this.sessionId }, { timeoutMs: STEER_TIMEOUT_MS })
  }

  /** session/cancel to every session the engine runs this session's turn on. */
  cancel(): void {
    for (const target of this.engine.cancelTargets()) this.host.conn.notify("session/cancel", { sessionId: target })
  }

  /**
   * Leave the host: the session is closed in kiro-cli (and deleted with `discard`) when kiro-cli
   * can close sessions (V3); otherwise it lives until its kiro-cli ends (V2). Lines that arrive
   * afterwards are not routed to the sink any more. Rejects with kiro-cli's error (the session is
   * gone here anyway).
   */
  async close(opts: { discard?: boolean } = {}): Promise<void> {
    this.drop()
    if (!this.host.canClose() || this.host.exited) return
    await this.engine.close()
    if (opts.discard) await this.engine.discard()
  }

  /** Leave the host without a request (the session was deleted, or the host ends). */
  drop(): void {
    this.host.remove(this)
  }
}

/** What a kiro-cli was started for. */
export type HostRole = "chat" | "composer" | "listing"

/** One kiro-cli and its one session. */
export class Host {
  readonly adapter: EngineAdapter
  /** What the engine advertised in its initialize answer (null until it answered). */
  caps: EngineCapabilities | null = null
  /** Its session's MCP servers, recorded since kiro-cli started. */
  readonly mcp = new McpRecord()
  session: HostSession | null = null
  lastActivity = Date.now()
  /** Initialize answered (rejects with the start's failure; the host is then killed). */
  readonly ready: Promise<void>
  /** kiro-cli's process tree. */
  readonly tree: ProcessTree
  /** The whole tree is gone (resolves once). */
  readonly gone: Promise<void>
  private markGone: () => void = () => {}
  private isGone = false
  /** Signals already sent (each kind once). */
  private readonly signalled = new Set<NodeJS.Signals>()
  private ending: Promise<void> = Promise.resolve()
  private poll: ReturnType<typeof setInterval> | null = null
  private escalation: ReturnType<typeof setTimeout> | null = null

  constructor(
    readonly engine: EngineId,
    readonly conn: AcpConnection,
    readonly role: HostRole,
    private readonly env: NodeJS.ProcessEnv,
    private readonly pool: HostPool,
    deps: Partial<ProcessDeps> = {},
  ) {
    this.adapter = adapterFor(engine)
    this.tree = new ProcessTree(conn.pid, deps)
    this.gone = new Promise((resolve) => { this.markGone = resolve })
    conn.onNotification((msg) => {
      for (const event of this.adapter.translateMcp(msg)) {
        if (event.type === "mcp_status" || event.type === "mcp_snapshot") this.mcp.apply(event)
      }
      const hs = this.session
      if (!hs) return
      const events = hs.engine.translate(msg)
      if (events.length) hs.sink.onEvents(events)
    })
    conn.onExit((code) => {
      this.tree.markExited()
      // A composer's slot is held until its tree is gone (its agent server or MCP servers may outlive it).
      if (role === "composer") void this.end("SIGTERM")
      else this.pool.forget(this)
      const hs = this.session
      this.session = null
      hs?.sink.onHostExit(code)
    })
    this.ready = this.initialize()
    this.ready.catch(() => {})
  }

  get exited(): boolean {
    return this.conn.exited
  }

  /** kiro-cli can end a session and keep running (session/close: V3). */
  canClose(): boolean {
    return this.caps?.session.close === true
  }

  /** A turn runs or work is held in its session. */
  busy(): boolean {
    return this.session?.sink.busy() ?? false
  }

  /** End kiro-cli and its process tree (SIGTERM, then SIGKILL if it is not gone in time). */
  kill(): void {
    if (this.role !== "composer") this.pool.forget(this)
    void this.end("SIGTERM")
  }

  /**
   * Send `signal` to the process tree (each kind once): a snapshot, then every recorded group.
   * From then on the tree is asked every GONE_POLL_MS whether it is gone; one not gone
   * COMPOSER_GONE_TIMEOUT_MS after SIGTERM gets SIGKILL, and one not gone that long after SIGKILL
   * is given up (warned; a composer's slot is freed).
   */
  end(signal: NodeJS.Signals): Promise<void> {
    if (this.isGone || this.signalled.has(signal)) return this.ending
    this.signalled.add(signal)
    const run = this.ending.then(() => this.tree.end(signal)).then(() => this.signalSent(signal))
    this.ending = run.catch((error: unknown) => console.warn("[acp] ending kiro-cli pid %s: %s", this.conn.pid, errorText(error)))
    return this.ending
  }

  /** Take a snapshot of the tree now (the session is ready: its servers are running). */
  snapshot(): void {
    void this.tree.snapshot()
  }

  private signalSent(signal: NodeJS.Signals): void {
    if (this.isGone) return
    if (!this.poll) {
      this.poll = setInterval(() => this.checkGone(), GONE_POLL_MS)
      this.poll.unref?.()
    }
    if (this.escalation) clearTimeout(this.escalation)
    this.escalation = setTimeout(() => this.notGoneInTime(signal), COMPOSER_GONE_TIMEOUT_MS)
    this.escalation.unref?.()
  }

  private notGoneInTime(signal: NodeJS.Signals): void {
    this.escalation = null
    if (this.checkGone()) return
    const groups = this.tree.groups().join(", ") || "none recorded"
    if (signal !== "SIGKILL") {
      console.warn("[acp] kiro-cli pid %s %s, groups %s still alive %d ms after %s; SIGKILL", this.conn.pid, this.exited ? "exited" : "runs", groups, COMPOSER_GONE_TIMEOUT_MS, signal)
      void this.end("SIGKILL")
      return
    }
    console.warn("[acp] kiro-cli pid %s: groups %s still alive %d ms after SIGKILL; giving it up", this.conn.pid, groups, COMPOSER_GONE_TIMEOUT_MS)
    this.finish()
  }

  private checkGone(): boolean {
    if (!this.tree.gone()) return false
    this.finish()
    return true
  }

  private finish(): void {
    if (this.isGone) return
    this.isGone = true
    if (this.poll) clearInterval(this.poll)
    if (this.escalation) clearTimeout(this.escalation)
    this.poll = null
    this.escalation = null
    this.pool.forget(this)
    this.markGone()
  }

  remove(hs: HostSession): void {
    if (this.session === hs) this.session = null
  }

  private async initialize(): Promise<void> {
    try {
      const init = await this.conn.request("initialize", INITIALIZE_PARAMS, { timeoutMs: INITIALIZE_TIMEOUT_MS }) as InitializeResponse
      this.caps = this.adapter.capabilities(init)
      console.log("[acp] started a %s kiro-cli (pid %s)", this.engine, this.conn.pid)
    } catch (error) {
      this.kill()
      if (error instanceof AgentTimeoutError) throw error
      if (this.conn.exited) {
        console.error("[acp] kiro-cli exited while starting (code %s): %s\n%s", this.conn.exitCode, errorText(error), this.conn.stderrTail().join("\n"))
        throw new AgentStartError("agent_start_failed", `kiro-cli exited while starting (code ${this.conn.exitCode}): ${errorText(error)}`)
      }
      throw error
    }
  }

  /**
   * Open a session for `sink` in `agentName`'s mode: a new one, a stored one (load) or a fork of a
   * stored one. The session is routed to the sink from its first request. Throws when the host
   * already carries a session. On failure (or an abort) the session is removed, a fork it made is
   * deleted, the host is killed and the error is rethrown: AbortError, AgentTimeoutError,
   * AgentStartError (also when kiro-cli exits while the session waits for the sdpm server),
   * HostOpenError `session_locked`, or kiro-cli's own.
   */
  async openSession(agentName: string, how: Open, opts: { signal?: AbortSignal; onPhase?: OpenPhase; sink: SessionSink }): Promise<{ hs: HostSession; outcome: LoadOutcome }> {
    const { signal } = opts
    if (signal?.aborted) throw abortError()
    if (this.exited) throw new AgentStartError("agent_start_failed", "kiro-cli exited")
    if (this.session) throw new Error("host already carries a session")
    /** Aborts the setup requests. */
    const requests = new AbortController()
    /** The fork this open made, deleted again if the open fails. */
    let forkId: string | null = null
    const ctx: SessionContext = {
      request: (method, params, requestOpts) => this.conn.request(method, params, requestOpts),
      cwd: MCP_LOCAL_DIR,
      env: this.env,
      setupTimeoutMs: SESSION_SETUP_TIMEOUT_MS,
      signal: requests.signal,
      waitForMcp: async (sessionId) => {
        // The wait ends with the caller's abort or kiro-cli's exit, not only with the server's state.
        const wait = new AbortController()
        const stop = () => wait.abort()
        signal?.addEventListener("abort", stop, { once: true })
        const unsubscribe = this.conn.onExit(stop)
        try {
          if (!(await waitForMcp(this.mcp, sessionId, SDPM_MCP_SERVER, MCP_READY_TIMEOUT_MS, wait.signal))) {
            console.warn("[acp] sdpm MCP server not connected after %dms (session %s); going on", MCP_READY_TIMEOUT_MS, sessionId)
          }
        } catch (error) {
          if (isAbort(error) && this.conn.exited && !signal?.aborted) {
            throw new AgentStartError("agent_start_failed", `kiro-cli exited while starting (code ${this.conn.exitCode})`)
          }
          throw error
        } finally {
          signal?.removeEventListener("abort", stop)
          unsubscribe()
        }
      },
      clearMcp: (sessionId) => this.mcp.clear(sessionId),
    }
    const hs = new HostSession(this, this.adapter.createSession(ctx), opts.sink)
    this.session = hs
    this.lastActivity = Date.now()
    // Cut the setup off at once, and end a kiro-cli that has no fork yet (a fork is deleted first).
    const onAbort = () => {
      requests.abort()
      if (!forkId) this.kill()
    }
    signal?.addEventListener("abort", onAbort, { once: true })
    try {
      let outcome: LoadOutcome = "created"
      if (how.kind === "fork") {
        const forked = await hs.engine.forkSession(how.sourceId, agentName, {
          onCopying: () => opts.onPhase?.("copying"),
          onForked: (id) => { forkId = id },
          onReplay: replayProgress(opts.onPhase),
          onSwitching: () => opts.onPhase?.("switching"),
        })
        hs.sessionId = forked.sessionId
        outcome = forked.outcome
      } else if (how.kind === "load") {
        const opened = await hs.engine.openSession(how.sessionId, agentName, {
          onReplay: replayProgress(opts.onPhase),
          onSwitching: () => opts.onPhase?.("switching"),
        })
        hs.sessionId = opened.sessionId
        outcome = opened.outcome
      } else {
        hs.sessionId = (await hs.engine.newSession(agentName)).sessionId
      }
      if (signal?.aborted) throw abortError()
      signal?.removeEventListener("abort", onAbort)
      this.snapshot()
      return { hs, outcome }
    } catch (error) {
      signal?.removeEventListener("abort", onAbort)
      const failure = this.openFailure(hs, error, signal)
      hs.drop()
      if (forkId) await discardFork(hs.engine, forkId)
      this.kill()
      throw failure
    }
  }

  /** What a failed open is reported as. */
  private openFailure(hs: HostSession, error: unknown, signal: AbortSignal | undefined): unknown {
    if (signal?.aborted || isAbort(error)) return isAbort(error) ? error : abortError()
    if (error instanceof AgentTimeoutError) return error
    if (error instanceof AgentStartError) {
      console.warn("[acp] %s: %s", error.code, error.message)
      return error
    }
    const kind = hs.engine.classifyError(error)
    if (kind === "session_locked") return new HostOpenError("session_locked", errorText(error))
    if (kind === "auth_required") {
      console.warn("[acp] agent_auth_required: %s", errorText(error))
      return new AgentStartError("agent_auth_required", errorText(error))
    }
    if (this.conn.exited) {
      console.error("[acp] kiro-cli exited while starting (code %s): %s\n%s", this.conn.exitCode, errorText(error), this.conn.stderrTail().join("\n"))
      return new AgentStartError("agent_start_failed", `kiro-cli exited while starting (code ${this.conn.exitCode}): ${errorText(error)}`)
    }
    return error
  }
}

/** Delete a fork through the session that made it; a failure is logged (the fork stays behind). */
export async function discardFork(engine: EngineSession, forkId: string): Promise<void> {
  try {
    await engine.discardFork(forkId)
    console.log("[acp] removed the fork %s", forkId)
  } catch (error) {
    console.warn("[acp] could not remove the fork %s: %s", forkId, errorText(error))
  }
}

/** First come, first served places for composer kiro-cli processes. */
class ComposerSlots {
  private taken = 0
  private readonly waiting: { resolve: () => void; reject: (error: unknown) => void; signal?: AbortSignal; onAbort: () => void }[] = []

  constructor(private readonly max: number) {}

  /** Every place is taken: a `take` now waits. */
  full(): boolean {
    return this.taken >= this.max
  }

  /** Resolves once a place is this caller's; an abort while waiting leaves the queue (AbortError). */
  take(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) return Promise.reject(abortError())
    if (this.taken < this.max && !this.waiting.length) {
      this.taken++
      return Promise.resolve()
    }
    return new Promise((resolve, reject) => {
      const entry = {
        resolve, reject, signal,
        onAbort: () => {
          const at = this.waiting.indexOf(entry)
          if (at >= 0) this.waiting.splice(at, 1)
          reject(abortError())
        },
      }
      signal?.addEventListener("abort", entry.onAbort, { once: true })
      this.waiting.push(entry)
    })
  }

  /** A place is free again: the oldest waiter gets it. */
  free(): void {
    const next = this.waiting.shift()
    if (next) {
      next.signal?.removeEventListener("abort", next.onAbort)
      next.resolve()
      return
    }
    this.taken = Math.max(0, this.taken - 1)
  }
}

/** The kiro-cli processes of this server. */
export class HostPool {
  private readonly hosts = new Set<Host>()
  private readonly slots = new ComposerSlots(MAX_COMPOSER_HOSTS)
  private readonly deps: ProcessDeps

  constructor(deps: Partial<ProcessDeps> = {}) {
    this.deps = { ...defaultProcessDeps, ...deps }
  }

  hostsOf(engine: EngineId): Host[] {
    return [...this.hosts].filter((host) => host.engine === engine && !host.exited)
  }

  /** Forget a host that ended (a chat's or listing's exit or kill; a composer's tree gone). A composer frees its slot. */
  forget(host: Host): void {
    if (this.hosts.delete(host) && host.role === "composer") this.slots.free()
  }

  /**
   * Start kiro-cli on `engine` with the current agent definitions and the chat environment, and
   * initialize it. The only way a kiro-cli is started.
   */
  async spawnHost(engine: EngineId, agentName: string, role: HostRole): Promise<Host> {
    const host = this.start(engine, agentName, role)
    await host.ready
    return host
  }

  /**
   * A kiro-cli of its own for a new chat (or a reopened deck, a fork) of `engine`, after the cap
   * made room. A start the chat gives up (`signal`) is killed.
   */
  async acquireForChat(engine: EngineId, agentName: string, opts: { signal?: AbortSignal } = {}): Promise<Host> {
    const { signal } = opts
    if (signal?.aborted) throw abortError()
    this.makeRoom()
    const host = this.start(engine, agentName, "chat")
    let onAbort = () => {}
    const aborted = new Promise<never>((_, reject) => {
      onAbort = () => reject(abortError())
      signal?.addEventListener("abort", onAbort, { once: true })
    })
    aborted.catch(() => {})
    try {
      await Promise.race([host.ready, aborted])
    } catch (error) {
      if (isAbort(error) && !host.exited) {
        console.log("[acp] the chat gave up the starting %s kiro-cli (pid %s); ending it", host.engine, host.conn.pid)
        host.kill()
      }
      throw error
    } finally {
      signal?.removeEventListener("abort", onAbort)
    }
    return host
  }

  /**
   * A connection for listing `engine`'s stored sessions: a live chat's kiro-cli of the engine,
   * else a new one, which `release` kills once the listing is done.
   */
  async acquireForListing(engine: EngineId): Promise<{ request: SessionContext["request"]; caps: EngineCapabilities; release: () => void }> {
    const request = (host: Host): SessionContext["request"] => (method, params, requestOpts) => host.conn.request(method, params, requestOpts)
    const chats = this.hostsOf(engine).filter((host) => host.role === "chat")
    const live = chats.find((host) => host.caps) ?? chats[0]
    if (live) {
      await live.ready
      return { request: request(live), caps: live.caps!, release: () => {} }
    }
    const host = await this.spawnHost(engine, LISTING_AGENT, "listing")
    console.log("[acp] the %s kiro-cli (pid %s) lists the stored sessions", engine, host.conn.pid)
    return {
      request: request(host),
      caps: host.caps!,
      release: () => host.kill(),
    }
  }

  /**
   * A kiro-cli of its own for one compose group: once a composer slot is free (`onWait` is called
   * when it has to wait), started for COMPOSER_AGENT on `engine` and initialized. An abort while
   * waiting leaves the queue; an abort during the start ends the starting tree with SIGKILL.
   */
  async acquireForComposer(engine: EngineId, opts: { signal?: AbortSignal; onWait?: () => void } = {}): Promise<Host> {
    const { signal } = opts
    if (signal?.aborted) throw abortError()
    if (this.slots.full()) opts.onWait?.()
    await this.slots.take(signal)
    let host: Host
    try {
      host = this.start(engine, COMPOSER_AGENT, "composer")
    } catch (error) {
      this.slots.free()
      throw error
    }
    let onAbort = () => {}
    const aborted = new Promise<never>((_, reject) => {
      onAbort = () => reject(abortError())
      signal?.addEventListener("abort", onAbort, { once: true })
    })
    aborted.catch(() => {})
    try {
      await Promise.race([host.ready, aborted])
    } catch (error) {
      if (isAbort(error)) void host.end("SIGKILL")
      throw error
    } finally {
      signal?.removeEventListener("abort", onAbort)
    }
    return host
  }

  /**
   * The Local server ends: every process tree is signalled now, synchronously, from one process
   * table (composer trees SIGKILL, chat and listing trees SIGTERM). Without a table, only the
   * kiro-cli pids (and a composer's own group) are signalled.
   */
  killAll(): void {
    const hosts = [...this.hosts]
    if (!hosts.length) return
    let table: ProcRow[] | null = null
    try {
      table = this.deps.tableSync()
    } catch (error) {
      console.warn("[acp] ps failed while ending every kiro-cli (%s); signalling their pids", errorText(error))
    }
    for (const host of hosts) {
      const signal: NodeJS.Signals = host.role === "composer" ? "SIGKILL" : "SIGTERM"
      if (table) {
        host.tree.record(table)
        host.tree.signal(signal, table)
        continue
      }
      const pid = host.conn.pid
      if (pid === undefined || host.exited) continue
      for (const target of host.role === "composer" ? [-pid, pid] : [pid]) {
        try {
          this.deps.kill(target, signal)
        } catch { /* gone */ }
      }
    }
  }

  private start(engine: EngineId, agentName: string, role: HostRole): Host {
    const adapter = adapterFor(engine)
    syncDefinitions()
    const config = readEngineConfig()
    const env: NodeJS.ProcessEnv = { ...process.env, ...config.env, SDPM_OUTPUT_DIR: DECK_ROOT, SDPM_DECK_ROOT: DECK_ROOT }
    // Last, whatever process.env or acp-config.json held: only a chat's sdpm server lists the compose tools.
    if (role === "composer") delete env[LOCAL_COMPOSE_ENV]
    else env[LOCAL_COMPOSE_ENV] = "1"
    const conn = spawnAcp(config.command, [...config.commandArgs, ...adapter.spawnArgs(agentName)], {
      cwd: MCP_LOCAL_DIR, env, ...(role === "composer" ? { detached: true } : {}),
    })
    const host = new Host(engine, conn, role, env, this, this.deps)
    this.hosts.add(host)
    return host
  }

  /** MAX_CHAT_HOSTS kiro-cli processes with a chat: release the least recently active one whose chat is idle. */
  private makeRoom(): void {
    const withChat = [...this.hosts].filter((host) => !host.exited && host.role === "chat" && host.session)
    if (withChat.length < MAX_CHAT_HOSTS) return
    const oldest = withChat.filter((host) => !host.busy()).sort((a, b) => a.session!.sink.lastActivity() - b.session!.sink.lastActivity())[0]
    if (!oldest) {
      console.warn("[acp] %d kiro-cli processes with a chat each are all busy; starting one more", withChat.length)
      return
    }
    const hs = oldest.session!
    void Promise.resolve(hs.sink.release()).catch((error: unknown) => console.warn("[acp] could not release session %s: %s", hs.sessionId, errorText(error)))
    if (!oldest.exited) oldest.kill()
  }
}

/** Re-derive `.kiro/agents/` (AgentStartError when it cannot). */
function syncDefinitions(): void {
  // Re-derived before every kiro-cli start (idempotent, all-or-nothing): a `git pull` that updates
  // the catalog takes effect on the next new chat.
  try {
    syncToAgentsDir()
  } catch (error) {
    console.error("[acp] agent definitions: %s", errorText(error))
    throw new AgentStartError("agent_start_failed", `agent definitions: ${errorText(error)}`)
  }
}

export const pool = new HostPool()

// End every kiro-cli when the Local server ends (registered once per Node process; tests re-import this module).
const CURRENT_POOL = Symbol.for("sdpm.local.hostPool")
const EXIT_HOOK = Symbol.for("sdpm.local.hostPool.exitHook")
const registry = globalThis as typeof globalThis & { [CURRENT_POOL]?: HostPool; [EXIT_HOOK]?: true }
registry[CURRENT_POOL] = pool
if (!registry[EXIT_HOOK]) {
  registry[EXIT_HOOK] = true
  for (const sig of ["exit", "SIGINT", "SIGTERM"] as const) {
    process.on(sig, () => { registry[CURRENT_POOL]?.killAll() })
  }
}
