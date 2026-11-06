// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The engine adapter contract and the registry of engines.
 *
 * kiro-cli runs an agent on one of its engines, which differ in how sessions are opened and what
 * their notifications look like. Everything that depends on the engine lives in its folder
 * (`engines/<id>/`) behind this interface; the process manager talks to the adapter, and the
 * conversation model reads only the adapter's `LocalEvent`s. Dropping an engine is removing its
 * folder and its line in `ADAPTERS`.
 *
 * The engine is chosen by configuration, never guessed from kiro-cli's answers; what an engine
 * can do is read from its initialize answer (`EngineCapabilities`).
 */
import type { LocalEvent } from "../conversation/events"
import type { McpReadyWatch } from "../mcp-ready"
import { v2Adapter } from "./engines/v2"
import type { AcpNotification, InitializeResponse } from "./schema"
import type { RequestOptions } from "./transport"

export type EngineId = "v2"

export interface EngineCapabilities {
  /** initialize's `agentCapabilities.sessionCapabilities` (V2 advertises none). */
  session: { list: boolean; close: boolean; delete: boolean; fork: boolean }
  /** The engine marks replayed updates; without it, updates before the load's answer are the replay. */
  replayMarking: boolean
  /** Extension methods the engine advertises. */
  extensionMethods: ReadonlySet<string>
  /** `_session/steer` is not advertised; assumed until kiro-cli answers it with Method not found. */
  steer: boolean
}

export type LoadOutcome = "resumed" | "created"

export interface AcpModel { modelId: string; name: string; description?: string }

export interface AcpModelList { current: string; available: AcpModel[] }

/** What a session gets from the process manager: its connection and the setup limits. */
export interface SessionContext {
  request(method: string, params?: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>
  /** The session's working directory (servers/local). */
  cwd: string
  /** Timeout of session/new, session/load and session/set_mode. */
  setupTimeoutMs: number
  /** How long to wait for the sdpm MCP server after set_mode. */
  mcpReadyTimeoutMs: number
  /** The caller's abort signal for the setup requests. */
  signal?: AbortSignal
  /** Watch for the sdpm MCP server of a session to report connected (`mcp_status`). */
  watchMcp(sessionId: string): McpReadyWatch
}

export interface OpenSessionOptions {
  /** Switch the opened session to `agentName`'s mode and wait for its sdpm server (a fork). */
  setMode?: boolean
  /**
   * The load's progress: called with 0 when the load starts, after each replayed update, and once
   * with `done` when kiro-cli answered the load.
   */
  onReplay?: (replayed: number, done: boolean) => void
  /** The session is being switched to the agent's mode. */
  onSwitching?: () => void
}

/** One kiro-cli process's conversation, as its engine runs it. */
export interface EngineSession {
  /** session/new. */
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
  /** The models session/new offered, or null before it answered. */
  models(): AcpModelList | null
}

export interface EngineAdapter {
  readonly id: EngineId
  capabilities(init: InitializeResponse): EngineCapabilities
  createSession(ctx: SessionContext): EngineSession
}

const ADAPTERS: Record<EngineId, EngineAdapter> = {
  v2: v2Adapter,
}

export function adapterFor(id: EngineId): EngineAdapter {
  return ADAPTERS[id]
}
