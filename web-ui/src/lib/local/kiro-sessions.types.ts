// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Shared types for "continue from a kiro-cli session" (Local mode only).
 *
 * kiro-cli stores every chat session (TUI and ACP alike) under
 * ~/.kiro/sessions/cli/{uuid}.json (+ .jsonl log). The Web UI lists those
 * sessions, forks the chosen one into a fresh UUID, and loads the fork via
 * ACP `session/load` so the user's earlier work becomes the deck's context.
 */

/** One kiro-cli session as shown in the picker. */
export interface KiroSessionSummary {
  sessionId: string
  /** `.json` title, or the first user prompt when the title is missing. */
  title: string
  /** Working directory the session was created in. */
  cwd: string
  /** `path.basename(cwd)` — the picker groups by this. */
  project: string
  /** ISO 8601 */
  updatedAt: string
  /** Number of user prompts in the `.jsonl` log. */
  messageCount: number
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
  /** Grouped by cwd, groups sorted by their newest session. */
  groups: KiroSessionGroup[]
  /** Updated within the last 24h, newest first, at most 3 — for the empty-state cards. */
  recent: KiroSessionSummary[]
}

/** Where a forked chat session came from. Persisted as `.session-origin.json` in the deck dir. */
export interface SessionOrigin {
  sourceSessionId: string
  title: string
  cwd: string
  /** Source session's `updated_at` at fork time (ISO 8601). */
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

export interface ForkSessionResponse {
  /** The forked session id. The client swaps its chat session id to this. */
  sessionId: string
  origin: SessionOrigin
}
