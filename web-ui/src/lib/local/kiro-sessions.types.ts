// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Shared types for "continue from a kiro-cli session" (Local mode only).
 *
 * kiro-cli saves every chat session (TUI and ACP alike) in the store of the agent engine that
 * ran it: V3's, which kiro-cli lists over ACP (`session/list`), and V2's files. The Web UI lists
 * the sessions the configured engine can open (on V3 both stores, on V2 only V2's), forks the
 * chosen one with that engine and loads the fork, so the user's earlier work becomes the deck's
 * context. The source session is not changed.
 */

/** The agent engine whose store holds a session (the server's EngineId, as a literal for the client). */
export type KiroSessionEngine = "v2" | "v3"

/** One kiro-cli session as shown in the picker. */
export interface KiroSessionSummary {
  sessionId: string
  engine: KiroSessionEngine
  /** The stored title (V2: or the first user prompt when the title is missing). */
  title: string
  /** Working directory the session was created in. */
  cwd: string
  /** `path.basename(cwd)` — the picker groups by this. */
  project: string
  /** ISO 8601 */
  updatedAt: string
  agentName: string | null
}

export interface KiroSessionGroup {
  cwd: string
  project: string
  /** Sorted by `updatedAt` desc. */
  sessions: KiroSessionSummary[]
}

/** GET /api/agent/sessions */
export interface KiroSessionsResponse {
  /** The configured agent engine (on V2, V3's sessions are not listed). */
  engine: KiroSessionEngine
  /** Grouped by cwd, groups sorted by their newest session. */
  groups: KiroSessionGroup[]
  /** Updated within the last 24h, newest first, at most 3 — for the empty-state cards. */
  recent: KiroSessionSummary[]
  /** Stores that could not be read (their sessions are missing from the list). */
  unavailable?: KiroSessionEngine[]
}

/** Where a forked chat session came from. Persisted as `.session-origin.json` in the deck dir. */
export interface SessionOrigin {
  sourceSessionId: string
  title: string
  cwd: string
  /** Source session's last update at fork time (ISO 8601). */
  updatedAt: string
  /** ISO 8601 */
  forkedAt: string
}

/** POST /api/agent/sessions/fork */
export interface ForkSessionRequest {
  sourceSessionId: string
  /** The client-side chat session id the fork should be registered under. */
  clientSessionId: string
  agentName?: string
}

/** In this order: kiro-cli starts, makes the fork, loads it, switches it to the agent's mode. */
export type ForkSessionPhase = "starting" | "copying" | "loading" | "switching"

export interface ForkSessionPhaseDetail {
  replayed?: number
}

export interface ForkSessionResponse {
  /** The forked session id. The client swaps its chat session id to this. */
  sessionId: string
  origin: SessionOrigin
}
