// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Host pool: the kiro-cli processes of the Local server. A *host* is one kiro-cli (one transport
 * connection, acp/transport.ts); a *host session* is one kiro session on it, read and written
 * through its engine's `EngineSession` (acp/engine.ts). Hosts know the chats that use their
 * sessions only as `SessionSink`s (chat.ts implements one; web-2's compose runs another).
 *
 * - Placement (`acquireForChat`) is decided by what kiro-cli advertises, never by the engine id:
 *   a host whose initialize answer has `sessionCapabilities.close` (V3) is *shared* and carries
 *   every new chat of its engine, at most MAX_CHATS_PER_SHARED_HOST open (the least recently
 *   active idle one is released for a new one); a host without it (V2) carries one chat, at most
 *   MAX_SINGLE_CHAT_HOSTS of them (the least recently active idle one is released). A busy sink is
 *   never released here: when every candidate is busy, the cap is exceeded with one warning.
 * - Every kiro-cli is started by `spawnHost`: the agent definitions are synced first (agents-sync,
 *   whose digest the host keeps), the chat environment (deck root included), initialize. A host
 *   started with other definitions than the current ones is retired: no new chat goes to it, and
 *   it ends when it has no chat left (or at the next spawn, once its chats are all idle).
 * - A start that every waiting chat gave up (their abort signals) is killed while no session is
 *   open on it yet. An open aborted on a shared host that carries other sessions is not cut off
 *   mid-request (kiro-cli would keep the session): it is deleted (new), closed (loaded) or
 *   discarded (fork) once kiro-cli answered.
 * - Routing: each line goes once through the adapter's `translateMcp` into the host's MCP record
 *   (mcp-ready.ts, keyed by session id, so a line from before any session knew its id counts),
 *   then to every host session's `translate`, whose events go to its sink.
 * - Listings (`acquireForListing`) use a live host of the engine; without one they start one,
 *   which stays in the pool when it is shared (the next chat uses it) and is killed otherwise.
 */
import path from "path"
import { syncToAgentsDir } from "./agents-sync"
import {
  adapterFor, type EngineAdapter, type EngineCapabilities, type EngineId, type EngineSession, type LoadOutcome, type SessionContext,
} from "./acp/engine"
import { readEngineConfig } from "./acp/engine-config"
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
/** Open chats on one shared host; a new one releases the least recently active idle chat. */
export const MAX_CHATS_PER_SHARED_HOST = 8
/** Single-chat hosts alive at once; a new one releases the least recently active idle one. */
export const MAX_SINGLE_CHAT_HOSTS = 3

/** What uses a host session: a chat (chat.ts) or a compose run's composer session (`aux`, web-2). */
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
   * Leave the host: on a shared host the session is closed in kiro-cli (and deleted with
   * `discard`); a single-chat host keeps it until it ends. Lines that arrive afterwards are not
   * routed to the sink any more. Rejects with kiro-cli's error (the session is gone here anyway).
   */
  async close(opts: { discard?: boolean } = {}): Promise<void> {
    this.drop()
    if (!this.host.shared() || this.host.exited) return
    await this.engine.close()
    if (opts.discard) await this.engine.discard()
  }

  /** Leave the host without a request (the session was deleted, or the host ends). */
  drop(): void {
    this.host.remove(this)
  }
}

/** One kiro-cli. */
export class Host {
  readonly adapter: EngineAdapter
  /** What the engine advertised in its initialize answer (null until it answered). */
  caps: EngineCapabilities | null = null
  /** Its sessions' MCP servers, recorded since kiro-cli started. */
  readonly mcp = new McpRecord()
  /** No new chat is placed here; it ends when it has no chat left. */
  retired = false
  readonly sessions = new Set<HostSession>()
  /** Composer (non-chat) sessions ever opened here; drives recycling on hosts without close. */
  auxOpened = 0
  lastActivity = Date.now()
  /** Initialize answered (rejects with the start's failure; the host is then killed). */
  readonly ready: Promise<void>
  /** Chats (and listings) waiting for this start. */
  waiters = 0
  private warnedFull = false

  constructor(
    readonly engine: EngineId,
    readonly conn: AcpConnection,
    readonly hostAgent: string,
    readonly agentsDigest: string,
    private readonly env: NodeJS.ProcessEnv,
    private readonly pool: HostPool,
  ) {
    this.adapter = adapterFor(engine)
    conn.onNotification((msg) => {
      for (const event of this.adapter.translateMcp(msg)) {
        if (event.type === "mcp_status" || event.type === "mcp_snapshot") this.mcp.apply(event)
      }
      for (const hs of [...this.sessions]) {
        if (!this.sessions.has(hs)) continue
        const events = hs.engine.translate(msg)
        if (events.length) hs.sink.onEvents(events)
      }
    })
    conn.onExit((code) => {
      this.pool.forget(this)
      for (const hs of [...this.sessions]) hs.sink.onHostExit(code)
      this.sessions.clear()
    })
    this.ready = this.initialize()
    this.ready.catch(() => {})
  }

  get exited(): boolean {
    return this.conn.exited
  }

  /** The host can close sessions, so it carries every chat of its engine. */
  shared(): boolean {
    return this.caps?.session.close === true
  }

  /** The sessions used by chats (not compose runs). */
  chatSessions(): HostSession[] {
    return [...this.sessions].filter((hs) => hs.sink.kind === "chat")
  }

  /** A turn runs or work is held in one of its sessions. */
  busy(): boolean {
    return [...this.sessions].some((hs) => hs.sink.busy())
  }

  kill(): void {
    this.pool.forget(this)
    this.conn.kill()
  }

  /** Warn once that every chat on this full host is busy. */
  warnFull(): void {
    if (this.warnedFull) return
    this.warnedFull = true
    console.warn("[acp] the %s kiro-cli (pid %s) carries %d busy chats; opening one more", this.engine, this.conn.pid, this.chatSessions().length)
  }

  /** A session left: a host that may not carry new chats ends with its last one. */
  remove(hs: HostSession): void {
    if (!this.sessions.delete(hs)) return
    if (this.sessions.size === 0 && this.retired && !this.exited) {
      console.log("[acp] the retired %s kiro-cli (pid %s) has no session left; ending it", this.engine, this.conn.pid)
      this.kill()
    }
  }

  private async initialize(): Promise<void> {
    try {
      const init = await this.conn.request("initialize", INITIALIZE_PARAMS, { timeoutMs: INITIALIZE_TIMEOUT_MS }) as InitializeResponse
      this.caps = this.adapter.capabilities(init)
      console.log("[acp] started a %s kiro-cli (pid %s)%s", this.engine, this.conn.pid, this.shared() ? " that carries every chat" : "")
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
   * stored one. The session is routed to the sink from its first request. On failure it is
   * removed (and cleaned up as the header says), the host is killed when it carries one chat or
   * no other session, and the error is rethrown: AbortError, AgentTimeoutError, AgentStartError,
   * HostOpenError `session_locked`, or kiro-cli's own.
   */
  async openSession(agentName: string, how: Open, opts: { signal?: AbortSignal; onPhase?: OpenPhase; sink: SessionSink }): Promise<{ hs: HostSession; outcome: LoadOutcome }> {
    const { signal } = opts
    if (signal?.aborted) throw abortError()
    if (this.exited) throw new AgentStartError("agent_start_failed", "kiro-cli exited")
    const shared = this.shared()
    /** Aborts the setup requests: only when nothing else uses this host (else kiro-cli would keep the session). */
    const requests = new AbortController()
    /** The fork this open made, deleted again if the open fails. */
    let forkId: string | null = null
    const ctx: SessionContext = {
      request: (method, params, requestOpts) => this.conn.request(method, params, requestOpts),
      cwd: MCP_LOCAL_DIR,
      env: this.env,
      setupTimeoutMs: SESSION_SETUP_TIMEOUT_MS,
      signal: requests.signal,
      hostAgent: this.hostAgent,
      waitForMcp: async (sessionId) => {
        if (!(await waitForMcp(this.mcp, sessionId, SDPM_MCP_SERVER, MCP_READY_TIMEOUT_MS, signal))) {
          console.warn("[acp] sdpm MCP server not connected after %dms (session %s); going on", MCP_READY_TIMEOUT_MS, sessionId)
        }
      },
      clearMcp: (sessionId) => this.mcp.clear(sessionId),
    }
    const hs = new HostSession(this, this.adapter.createSession(ctx), opts.sink)
    this.sessions.add(hs)
    if (opts.sink.kind === "aux") this.auxOpened++
    this.lastActivity = Date.now()
    /** Nothing else uses this kiro-cli (a single-chat host is its chat's). */
    const alone = () => (this.sessions.size === 1 && this.waiters === 0) || (!shared && opts.sink.kind === "chat")
    // Alone on the host: cut the setup off at once, and end a kiro-cli that has no fork yet.
    const onAbort = () => {
      if (!alone()) return
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
      return { hs, outcome }
    } catch (error) {
      signal?.removeEventListener("abort", onAbort)
      const failure = this.openFailure(hs, error, signal)
      const kill = alone() || this.exited
      hs.drop()
      if (forkId) await discardFork(hs.engine, forkId)
      if (!kill && !forkId) await this.endAbandoned(hs, how)
      if (kill) this.kill()
      throw failure
    }
  }

  /** A session this host opened for a caller that gave up: deleted when it was new, closed when it was loaded. */
  private async endAbandoned(hs: HostSession, how: Open): Promise<void> {
    if (!this.shared() || this.exited) return
    try {
      if (how.kind === "new") await hs.engine.discard()
      else await hs.engine.close()
      console.log("[acp] %s the session %s nobody waits for any more", how.kind === "new" ? "deleted" : "closed", hs.sessionId ?? "(no id)")
    } catch (error) {
      console.warn("[acp] could not end the abandoned session %s: %s", hs.sessionId ?? "(no id)", errorText(error))
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

/** The kiro-cli processes of this server. */
export class HostPool {
  private readonly hosts = new Set<Host>()
  /** Engines whose last started host was shared (a new host of theirs is expected to be one). */
  private readonly sharedEngines = new Set<EngineId>()

  hostsOf(engine: EngineId): Host[] {
    return [...this.hosts].filter((host) => host.engine === engine && !host.exited)
  }

  /** Forget a host that ended (its exit, a kill). */
  forget(host: Host): void {
    this.hosts.delete(host)
  }

  /**
   * Start kiro-cli on `engine` with the current agent definitions and the chat environment, and
   * initialize it. The only way a kiro-cli is started. Retired hosts whose chats are all idle end first.
   */
  async spawnHost(engine: EngineId, agentName: string): Promise<Host> {
    const host = this.start(engine, agentName)
    host.waiters++
    try {
      await host.ready
    } finally {
      host.waiters--
    }
    return host
  }

  /**
   * The host for a new chat (or a reopened deck, a fork) of `engine`: the live shared host with
   * the current definitions, after it made room; else a new kiro-cli, after the single-chat cap
   * made room. A start this chat waits for is killed when every chat waiting for it gave up.
   */
  async acquireForChat(engine: EngineId, agentName: string, opts: { signal?: AbortSignal } = {}): Promise<Host> {
    const { signal } = opts
    if (signal?.aborted) throw abortError()
    const digest = syncDefinitions(adapterFor(engine))
    for (const host of this.hostsOf(engine)) {
      if (!host.retired && host.agentsDigest !== digest) this.retire(host, "its agent definitions changed")
    }
    for (;;) {
      const candidates = this.hostsOf(engine).filter((host) => !host.retired && host.agentsDigest === digest)
      const shared = candidates.find((host) => host.shared())
      if (shared) {
        this.makeRoom(shared)
        return shared
      }
      const starting = candidates.find((host) => host.caps === null)
      if (!starting) break
      // A start of this engine is under way: it may turn out shared.
      await this.wait(starting, signal)
    }
    if (!this.sharedEngines.has(engine)) this.makeSingleChatRoom()
    const host = this.start(engine, agentName, digest)
    await this.wait(host, signal)
    return host
  }

  /**
   * A connection for listing `engine`'s stored sessions: a live host of the engine (any
   * definitions), else a new one. `release` kills a new host that cannot carry chats.
   */
  async acquireForListing(engine: EngineId): Promise<{ request: SessionContext["request"]; caps: EngineCapabilities; release: () => void }> {
    const request = (host: Host): SessionContext["request"] => (method, params, requestOpts) => host.conn.request(method, params, requestOpts)
    const live = this.hostsOf(engine).find((host) => host.caps) ?? this.hostsOf(engine)[0]
    if (live) {
      live.waiters++
      try {
        await live.ready
      } finally {
        live.waiters--
      }
      return { request: request(live), caps: live.caps!, release: () => {} }
    }
    const host = await this.spawnHost(engine, LISTING_AGENT)
    console.log("[acp] the %s kiro-cli (pid %s) lists the stored sessions", engine, host.conn.pid)
    return {
      request: request(host),
      caps: host.caps!,
      release: () => { if (!host.shared() && host.sessions.size === 0) host.kill() },
    }
  }

  /** A Settings switch: the hosts of `engine` take no new chats and end once they have none. */
  retireEngine(engine: EngineId): void {
    for (const host of this.hostsOf(engine)) this.retire(host, "the agent engine changed")
  }

  killAll(): void {
    for (const host of [...this.hosts]) host.kill()
  }

  private retire(host: Host, why: string): void {
    if (host.retired) return
    host.retired = true
    console.log("[acp] %s: the %s kiro-cli (pid %s) takes no new chats", why, host.engine, host.conn.pid)
    if (host.sessions.size === 0 && host.waiters === 0) host.kill()
  }

  private start(engine: EngineId, agentName: string, digest?: string): Host {
    this.endIdleRetired()
    const adapter = adapterFor(engine)
    const agentsDigest = digest ?? syncDefinitions(adapter)
    const config = readEngineConfig()
    const env = { ...process.env, ...config.env, SDPM_OUTPUT_DIR: DECK_ROOT, SDPM_DECK_ROOT: DECK_ROOT }
    const conn = spawnAcp(config.command, [...config.commandArgs, ...adapter.spawnArgs(agentName)], { cwd: MCP_LOCAL_DIR, env })
    const host = new Host(engine, conn, agentName, agentsDigest, env, this)
    this.hosts.add(host)
    host.ready.then(() => {
      if (host.shared()) this.sharedEngines.add(engine)
      else this.sharedEngines.delete(engine)
    }, () => {})
    return host
  }

  /** Wait for a host's initialize as one of its waiters; the last waiter to give up kills a start with no session. */
  private async wait(host: Host, signal: AbortSignal | undefined): Promise<void> {
    if (signal?.aborted) throw abortError()
    host.waiters++
    let onAbort = () => {}
    const aborted = new Promise<never>((_, reject) => {
      onAbort = () => {
        reject(abortError())
      }
      signal?.addEventListener("abort", onAbort, { once: true })
    })
    aborted.catch(() => {})
    try {
      await Promise.race([host.ready, aborted])
    } finally {
      signal?.removeEventListener("abort", onAbort)
      host.waiters--
      if (signal?.aborted && host.waiters === 0 && host.sessions.size === 0 && !host.exited) {
        console.log("[acp] no chat waits for the starting %s kiro-cli (pid %s) any more; ending it", host.engine, host.conn.pid)
        host.kill()
      }
    }
  }

  /** A shared host with MAX_CHATS_PER_SHARED_HOST chats: release the least recently active idle one. */
  private makeRoom(host: Host): void {
    const chats = host.chatSessions()
    if (chats.length < MAX_CHATS_PER_SHARED_HOST) return
    const idle = chats.filter((hs) => !hs.sink.busy()).sort((a, b) => a.sink.lastActivity() - b.sink.lastActivity())[0]
    if (!idle) {
      host.warnFull()
      return
    }
    console.log("[acp] the %s kiro-cli carries %d chats; closing the least recently used idle one (session %s)", host.engine, chats.length, idle.sessionId)
    void Promise.resolve(idle.sink.release()).catch((error: unknown) => console.warn("[acp] could not release session %s: %s", idle.sessionId, errorText(error)))
  }

  /** MAX_SINGLE_CHAT_HOSTS single-chat hosts with a chat: release the least recently active one whose chats are idle. */
  private makeSingleChatRoom(): void {
    const single = [...this.hosts].filter((host) => !host.exited && host.caps && !host.shared() && host.chatSessions().length > 0)
    if (single.length < MAX_SINGLE_CHAT_HOSTS) return
    const lastActivity = (host: Host) => Math.max(...host.chatSessions().map((hs) => hs.sink.lastActivity()))
    const oldest = single.filter((host) => !host.busy()).sort((a, b) => lastActivity(a) - lastActivity(b))[0]
    if (!oldest) {
      console.warn("[acp] %d kiro-cli processes with one chat each are all busy; starting one more", single.length)
      return
    }
    for (const hs of oldest.chatSessions()) {
      void Promise.resolve(hs.sink.release()).catch((error: unknown) => console.warn("[acp] could not release session %s: %s", hs.sessionId, errorText(error)))
    }
    if (!oldest.exited) oldest.kill()
  }

  /** Retired hosts whose chats are all idle end now (each chat released first). */
  private endIdleRetired(): void {
    for (const host of [...this.hosts]) {
      if (!host.retired || host.exited || host.busy()) continue
      for (const hs of host.chatSessions()) {
        void Promise.resolve(hs.sink.release()).catch((error: unknown) => console.warn("[acp] could not release session %s: %s", hs.sessionId, errorText(error)))
      }
      if (!host.exited) host.kill()
    }
  }
}

/** Re-derive `.kiro/agents/` for `adapter`'s engine and return its digest (AgentStartError when it cannot). */
function syncDefinitions(adapter: EngineAdapter): string {
  // Re-derived before every placement (idempotent, all-or-nothing): a `git pull` that updates the
  // catalog takes effect on the next new chat. An engine whose sub-agents follow the session's
  // model gets no model in the composer's definition, so the composer runs on the chat's choice.
  try {
    return syncToAgentsDir(undefined, undefined, { pinSubagentModel: !adapter.subagentsFollowSessionModel })
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
