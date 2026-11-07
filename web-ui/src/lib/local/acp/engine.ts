// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The engine adapter contract and the registry of engines.
 *
 * kiro-cli runs an agent on one of its engines, which differ in how kiro-cli is started, how
 * sessions are opened and what their notifications look like. Everything that depends on the
 * engine lives in its folder (`engines/<id>/`) behind this interface; the process manager talks
 * to the adapter, and the conversation model reads only the adapter's `LocalEvent`s. Dropping an
 * engine is removing its folder, its line in `ADAPTERS` and its id in `ENGINE_IDS`
 * (engine-config.ts) and Settings.
 *
 * The engine is chosen by configuration (`readEngineConfig().engine`), never guessed from
 * kiro-cli's answers; what an engine can do is read from its initialize answer (`EngineCapabilities`).
 */
import type { LocalEvent } from "../conversation/events"
import type { EngineId } from "./engine-config"
import { v2Adapter } from "./engines/v2"
import { v3Adapter } from "./engines/v3"
import type { AcpNotification, InitializeResponse } from "./schema"
import type { RequestOptions } from "./transport"

export type { EngineId }

export interface EngineCapabilities {
  /** initialize's `agentCapabilities.sessionCapabilities` (V3: list, close, delete, fork; V2: none). For phase 3. */
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

export interface AcpModel { modelId: string; name: string; description?: string }

export interface AcpModelList { current: string; available: AcpModel[] }

/** What a session gets from the process manager: its connection, the setup limits and the MCP record. */
export interface SessionContext {
  request(method: string, params?: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>
  /** The session's working directory (servers/local). */
  cwd: string
  /** Timeout of session/new, session/load and session/set_mode. */
  setupTimeoutMs: number
  /** The caller's abort signal for the setup requests. */
  signal?: AbortSignal
  /**
   * Wait for the session's sdpm MCP server, as recorded since kiro-cli started (mcp-ready.ts):
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

/**
 * One kiro-cli process's conversation, as its engine runs it. `newSession` and `openSession`
 * return once the session runs the requested agent's mode (else AgentStartError
 * `agent_definition_rejected`) and its sdpm server is ready (`ctx.waitForMcp`).
 */
export interface EngineSession {
  newSession(agentName: string): Promise<{ sessionId: string }>
  /** Open an existing session; `sessionId` in the answer is the one prompts go to. */
  openSession(sessionId: string, agentName: string, opts?: OpenSessionOptions): Promise<{ sessionId: string; outcome: LoadOutcome }>
  /** One kiro-cli notification as engine-independent events; replays and internal notifications are []. */
  translate(msg: AcpNotification): LocalEvent[]
  /** A prompt turn starts / ends (the process manager's turn, which steers may continue). */
  beginTurn(): void
  endTurn(): void
  /** Where Stop sends session/cancel. */
  cancelTargets(): string[]
  /** The models the session offers, or null before kiro-cli reported them. */
  models(): AcpModelList | null
  classifyError(error: unknown): EngineErrorKind | null
}

export interface EngineAdapter {
  readonly id: EngineId
  /** kiro-cli's arguments after the configured command and commandArgs. */
  spawnArgs(agentName: string): string[]
  capabilities(init: InitializeResponse): EngineCapabilities
  createSession(ctx: SessionContext): EngineSession
}

const ADAPTERS: Record<EngineId, EngineAdapter> = {
  v2: v2Adapter,
  v3: v3Adapter,
}

export function adapterFor(id: EngineId): EngineAdapter {
  return ADAPTERS[id]
}
