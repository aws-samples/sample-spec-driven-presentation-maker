// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The engine adapter contract and the registry of engines.
 *
 * kiro-cli runs an agent on one of its engines, which differ in how kiro-cli is started, how
 * sessions are opened and what their notifications look like. Everything that depends on the
 * engine lives in its folder (`engines/<id>/`) behind this interface; the host pool (hosts.ts)
 * talks to the adapter, and the conversation model reads only the adapter's `LocalEvent`s. One
 * kiro-cli may carry several sessions: the adapter reads each line's MCP state once
 * (`translateMcp`), and each `EngineSession` (one kiro session) reads its own session's events. Dropping an
 * engine is removing its folder, its line in `ADAPTERS` and its id in `ENGINE_IDS`
 * (engine-config.ts) and Settings.
 *
 * The engine is chosen by configuration (`readEngineConfig().engine`), never guessed from
 * kiro-cli's answers; what an engine can do is read from its initialize answer (`EngineCapabilities`).
 *
 * Each engine also owns the store it saves sessions in (`listStoredSessions`) and declares which
 * engines can open them (`sessionsOpenableBy`): the session catalog (kiro-sessions.ts) lists the
 * stores the configured engine can open, and the engine's session forks one of them.
 */
import type { LocalEvent } from "../conversation/events"
import type { EngineId } from "./engine-config"
import { v2Adapter } from "./engines/v2"
import { v3Adapter } from "./engines/v3"
import type { AcpNotification, InitializeResponse } from "./schema"
import type { RequestOptions } from "./transport"

export type { EngineId }

export interface EngineCapabilities {
  /**
   * initialize's `agentCapabilities.sessionCapabilities` (V3: list, close, delete, fork; V2: none).
   * `close`: one session can be ended and the kiro-cli's others kept (hosts.ts `HostSession.close`).
   */
  session: { list: boolean; close: boolean; delete: boolean; fork: boolean }
  /** The engine marks replayed updates; without it, updates before the load's answer are the replay. */
  replayMarking: boolean
  /** Extension methods the engine advertises (kept, not used yet). */
  extensionMethods: ReadonlySet<string>
  /** `_session/steer` is not advertised; assumed until kiro-cli answers it with Method not found. */
  steer: boolean
}

/** `created`: kiro-cli did not have the session, and the conversation starts empty. */
export type LoadOutcome = "resumed" | "created"

/** What an engine recognises in an error kiro-cli answered (its texts and codes stay in the adapter). */
export type EngineErrorKind = "session_locked" | "auth_required"

/** A model the session offers. `effortLevels` / `defaultEffort` only for a model with effort levels; `rate` is kiro-cli's credit multiplier. */
export interface ModelOption {
  modelId: string
  name: string
  description?: string
  effortLevels?: string[]
  defaultEffort?: string
  rate?: number
}

/** The session's model and the models it offers; `effort` is the current model's effort (null when it has none). */
export interface SessionModels {
  current: string
  available: ModelOption[]
  effort: { current: string; levels: string[] } | null
}

/** A change of the session's model and/or effort. */
export interface ModelChoice {
  model?: string
  effort?: string
}

/** What a session gets from its host (hosts.ts): the host's connection, the setup limits and the host's MCP record. */
export interface SessionContext {
  request(method: string, params?: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>
  /** The session's working directory (servers/local). */
  cwd: string
  /** The environment kiro-cli runs with (where its stores are: `KIRO_HOME`). */
  env: NodeJS.ProcessEnv
  /** Timeout of session/new, session/load and session/set_mode. */
  setupTimeoutMs: number
  /** The caller's abort signal for the setup requests. */
  signal?: AbortSignal
  /** The agent the kiro-cli was started with (V2's `--agent`; V3 ignores it). */
  hostAgent: string
  /**
   * Wait for the session's sdpm MCP server, as recorded on the host since kiro-cli started (mcp-ready.ts):
   * resolves when it is connected or the wait timed out (logged), rejects with McpFailedError.
   */
  waitForMcp(sessionId: string): Promise<void>
  /** Forget the session's recorded MCP state (before set_mode). */
  clearMcp(sessionId: string): void
}

export interface OpenSessionOptions {
  /**
   * The load's progress: called with 0 when the load starts, after each replayed update, and once
   * with `done` when kiro-cli answered the load.
   */
  onReplay?: (replayed: number, done: boolean) => void
  /** The session is being switched to the agent's mode. */
  onSwitching?: () => void
}

export interface ForkSessionOptions extends OpenSessionOptions {
  /** The fork is being made. */
  onCopying?: () => void
  /** The fork exists under this id (before it is opened): a failure from here on leaves it to `discardFork`. */
  onForked?: (sessionId: string) => void
}

/** A session saved in an engine's store, as the session picker lists it. */
export interface StoredSession {
  sessionId: string
  /** The engine whose store holds it. */
  engine: EngineId
  title: string
  /** Working directory the session was created in. */
  cwd: string
  /** ISO 8601 ("" when unknown). */
  updatedAt: string
  /** The agent (V2) or mode (V3) it ran, when known. */
  agentName: string | null
  /** A sub-agent's own session (V2), listed only with "Show all". */
  subagent?: boolean
}

/** What an engine's store is read with: kiro-cli's environment and, when the store needs one, a connection. */
export interface StoreContext {
  env: NodeJS.ProcessEnv
  /** An initialized kiro-cli of this engine (the registry's `withEngineConnection`, over the host pool). */
  connect(): Promise<{ request: SessionContext["request"]; caps: EngineCapabilities }>
}

/**
 * One kiro session, as its engine runs it (a kiro-cli may carry several). `newSession` and
 * `openSession` open the requested agent's mode on any kiro-cli of the engine, whatever agent it
 * was started with, and return once the session runs that mode (else AgentStartError
 * `agent_definition_rejected`) and its sdpm server is ready (`ctx.waitForMcp`).
 */
export interface EngineSession {
  newSession(agentName: string): Promise<{ sessionId: string }>
  /** Open an existing session; `sessionId` in the answer is the one prompts go to. */
  openSession(sessionId: string, agentName: string, opts?: OpenSessionOptions): Promise<{ sessionId: string; outcome: LoadOutcome }>
  /**
   * Make a new session from a stored one (any store this engine can open) and open it; the source
   * is left as it is. `sessionId` is the fork's. `created`: kiro-cli could not read the fork, and
   * its conversation would start empty.
   */
  forkSession(sourceId: string, agentName: string, opts?: ForkSessionOptions): Promise<{ sessionId: string; outcome: LoadOutcome }>
  /** Delete a session this session forked (any other id is ignored with a warning). */
  discardFork(sessionId: string): Promise<void>
  /**
   * One kiro-cli notification as engine-independent events of this session (and of the sub-agent
   * sessions it maps, V2); another session's lines, replays, internal notifications and MCP state
   * (`EngineAdapter.translateMcp`) are [].
   */
  translate(msg: AcpNotification): LocalEvent[]
  /** A prompt turn starts / ends (the process manager's turn, which steers may continue). */
  beginTurn(): void
  endTurn(): void
  /** Where Stop sends session/cancel. */
  cancelTargets(): string[]
  /**
   * The session's model, its effort and the models it offers (kiro-cli's `[Internal]` and
   * `[Deprecated]` ones left out), or null before kiro-cli reported them.
   */
  models(): SessionModels | null
  /**
   * Change the session's model, then its effort. The caller validated the choice against
   * `models()`; rejects with the request's error (an effort the engine cannot set included).
   */
  setModel(choice: ModelChoice): Promise<void>
  classifyError(error: unknown): EngineErrorKind | null
  /** End the session in kiro-cli (V3 `session/close`; V2 cannot, and resolves). No-op before it has an id. */
  close(): Promise<void>
  /** Delete the session from kiro-cli's store (V3 `session/delete`; V2 no-op). No-op before it has an id. */
  discard(): Promise<void>
}

export interface EngineAdapter {
  readonly id: EngineId
  /** kiro-cli's arguments after the configured command and commandArgs. */
  spawnArgs(agentName: string): string[]
  capabilities(init: InitializeResponse): EngineCapabilities
  /** The `EngineSession` of one kiro session on a kiro-cli of this engine. */
  createSession(ctx: SessionContext): EngineSession
  /**
   * A line's MCP state (`mcp_status` / `mcp_snapshot`), whichever session it names, also one no
   * session knows the id of yet; [] for any other line. The host applies it once per line.
   */
  translateMcp(msg: AcpNotification): LocalEvent[]
  /** The engines that can open (fork) the sessions in this engine's store. */
  readonly sessionsOpenableBy: readonly EngineId[]
  /** The sessions in this engine's store. */
  listStoredSessions(ctx: StoreContext): Promise<StoredSession[]>
  /**
   * A sub-agent whose definition names no model runs on the session's model and effort (V3).
   * When false, agents-sync writes the Settings model into the composer's definition too.
   */
  readonly subagentsFollowSessionModel: boolean
}

const ADAPTERS: Record<EngineId, EngineAdapter> = {
  v2: v2Adapter,
  v3: v3Adapter,
}

export function adapterFor(id: EngineId): EngineAdapter {
  return ADAPTERS[id]
}

/** The adapters whose stored sessions `engine` can open. */
export function storedSessionAdapters(engine: EngineId): EngineAdapter[] {
  return Object.values(ADAPTERS).filter((adapter) => adapter.sessionsOpenableBy.includes(engine))
}
