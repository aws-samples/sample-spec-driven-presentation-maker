// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The last known state of a Cloud session, kept in localStorage (`sdpm-session:<id>`).
 *
 * A page that opens a deck reconnects to its session only when the last state it saw
 * was "working" (R5: no reconnect, and so no VM kept alive, for a session that is idle).
 * `at` is when the state was last written; a "working" state older than RESUME_WINDOW_MS
 * (the 60-minute work limit plus a margin) is not trusted.
 */

export type SessionRunState = "working" | "idle"

export interface StoredSessionState {
  state: SessionRunState
  lastSeq: number
  at: number
}

export const RESUME_WINDOW_MS = 65 * 60 * 1000
/** Seq-only updates are written at most this often; a state change is written at once. */
export const WRITE_INTERVAL_MS = 1000

const key = (sessionId: string) => `sdpm-session:${sessionId}`

export function readSessionState(sessionId: string): StoredSessionState | null {
  try {
    const raw = localStorage.getItem(key(sessionId))
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<StoredSessionState>
    if (value.state !== "working" && value.state !== "idle") return null
    return {
      state: value.state,
      lastSeq: typeof value.lastSeq === "number" ? value.lastSeq : 0,
      at: typeof value.at === "number" ? value.at : 0,
    }
  } catch {
    return null
  }
}

/** True when the last known state is "working" and recent enough to reconnect to. */
export function isResumable(sessionId: string, now: number = Date.now()): boolean {
  const stored = readSessionState(sessionId)
  return !!stored && stored.state === "working" && now - stored.at < RESUME_WINDOW_MS
}

function write(sessionId: string, state: SessionRunState, lastSeq: number): void {
  try {
    localStorage.setItem(key(sessionId), JSON.stringify({ state, lastSeq, at: Date.now() }))
  } catch { /* storage full or unavailable: reconnect after reload is best effort */ }
}

export interface SessionStateWriter {
  update: (state: SessionRunState, lastSeq: number) => void
  /** Write a pending update now. */
  flush: () => void
}

/** A writer for one session: state changes go out at once, seq updates at most once a second. */
export function createSessionStateWriter(sessionId: string): SessionStateWriter {
  let written: SessionRunState | null = null
  let lastWrite = 0
  let pending: { state: SessionRunState; lastSeq: number } | null = null
  let timer: ReturnType<typeof setTimeout> | null = null

  const flush = () => {
    if (timer) { clearTimeout(timer); timer = null }
    if (!pending) return
    write(sessionId, pending.state, pending.lastSeq)
    written = pending.state
    lastWrite = Date.now()
    pending = null
  }

  const update = (state: SessionRunState, lastSeq: number) => {
    pending = { state, lastSeq }
    if (state !== written || Date.now() - lastWrite >= WRITE_INTERVAL_MS) {
      flush()
      return
    }
    if (!timer) timer = setTimeout(flush, WRITE_INTERVAL_MS - (Date.now() - lastWrite))
  }

  return { update, flush }
}
