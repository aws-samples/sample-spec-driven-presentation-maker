// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local-only catalog of kiro-cli's stored sessions, for "Continue from a kiro session".
 *
 * The configured engine decides what is listed: the stores of every engine whose sessions it can
 * open (`storedSessionAdapters`; each engine reads its own store in `acp/engines/<id>/`). The
 * sessions are filtered first (sdpm's own sessions and sub-agent sessions only with "Show all"),
 * then one row is kept per session id: the configured engine's own row over a row of a store it
 * imports from (it continues its own copy), else the newer one. A store that cannot be read is
 * reported in `unavailable` and the others are still listed.
 */
import path from "path"

import { storedSessionAdapters, type EngineId, type StoredSession } from "./acp/engine"
import { readEngineConfig } from "./acp/engine-config"
import { withEngineConnection } from "./acp-process"
import type { KiroSessionSummary, KiroSessionsResponse } from "./kiro-sessions.types"

const RECENT_WINDOW_MS = 24 * 60 * 60 * 1000
const RECENT_COUNT = 3

/** A session the picker lists by default: no sdpm agent, not started in servers/local, not a sub-agent's. */
export function isCandidate(session: Pick<StoredSession, "cwd" | "agentName" | "subagent">): boolean {
  return !session.subagent
    && !session.agentName?.startsWith("sdpm-")
    && !/[\\/]servers[\\/]local(?:[\\/]|$)/.test(session.cwd)
}

interface Listing {
  engine: EngineId
  sessions: StoredSession[]
  unavailable: EngineId[]
}

/** One listing per engine at a time: concurrent requests share it. */
const inFlight = new Map<EngineId, Promise<Listing>>()
/** The last listing's sessions by id (candidates' rows first), for `findSession`. */
let cache: { engine: EngineId; sessions: Map<string, StoredSession> } | null = null

function updatedTime(session: { updatedAt: string }): number {
  const timestamp = Date.parse(session.updatedAt)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

/** Every stored session the engine can open, read from each store. */
function readStores(engine: EngineId): Promise<Listing> {
  const running = inFlight.get(engine)
  if (running) return running
  const listing = (async () => {
    const env = { ...process.env, ...readEngineConfig().env }
    const unavailable: EngineId[] = []
    const stores = await Promise.all(storedSessionAdapters(engine).map(async (adapter) => {
      try {
        return await withEngineConnection(adapter.id, (connect) => adapter.listStoredSessions({ env, connect }))
      } catch (error) {
        console.warn("[kiro-sessions] could not list the %s sessions: %s", adapter.id, error instanceof Error ? error.message : String(error))
        unavailable.push(adapter.id)
        return []
      }
    }))
    return { engine, sessions: stores.flat(), unavailable }
  })().finally(() => inFlight.delete(engine))
  inFlight.set(engine, listing)
  return listing
}

/** One row per session id: the engine's own row over an imported store's, else the newer. */
function dedupe(sessions: StoredSession[], engine: EngineId): StoredSession[] {
  const kept = new Map<string, StoredSession>()
  for (const session of sessions) {
    const other = kept.get(session.sessionId)
    if (!other) kept.set(session.sessionId, session)
    else if (other.engine !== session.engine) {
      if (session.engine === engine) kept.set(session.sessionId, session)
    } else if (updatedTime(session) > updatedTime(other)) kept.set(session.sessionId, session)
  }
  return [...kept.values()]
}

function summary(session: StoredSession): KiroSessionSummary {
  return {
    sessionId: session.sessionId,
    engine: session.engine,
    title: session.title,
    cwd: session.cwd,
    project: path.basename(session.cwd),
    updatedAt: session.updatedAt,
    agentName: session.agentName,
  }
}

export async function listSessions(opts: { includeAll: boolean }): Promise<KiroSessionsResponse> {
  const engine = readEngineConfig().engine
  const listing = await readStores(engine)
  const candidates = dedupe(listing.sessions.filter(isCandidate), engine)
  const all = dedupe(listing.sessions, engine)
  const sessions = new Map(candidates.map((session) => [session.sessionId, session]))
  for (const session of all) if (!sessions.has(session.sessionId)) sessions.set(session.sessionId, session)
  cache = { engine, sessions }

  const listed = (opts.includeAll ? [...sessions.values()] : candidates).sort((a, b) => updatedTime(b) - updatedTime(a))
  const grouped = new Map<string, KiroSessionSummary[]>()
  for (const session of listed) {
    const group = grouped.get(session.cwd) ?? []
    group.push(summary(session))
    grouped.set(session.cwd, group)
  }
  const groups = Array.from(grouped, ([cwd, rows]) => ({ cwd, project: rows[0]?.project ?? path.basename(cwd), sessions: rows }))
  const cutoff = Date.now() - RECENT_WINDOW_MS
  const recent = candidates
    .filter((session) => updatedTime(session) >= cutoff)
    .sort((a, b) => updatedTime(b) - updatedTime(a))
    .slice(0, RECENT_COUNT)
    .map(summary)

  return { engine, groups, recent, ...(listing.unavailable.length ? { unavailable: listing.unavailable } : {}) }
}

/** A stored session the configured engine can open: from the last listing, else a fresh full one. */
export async function findSession(sessionId: string): Promise<StoredSession | null> {
  const engine = readEngineConfig().engine
  const cached = cache?.engine === engine ? cache.sessions.get(sessionId) : undefined
  if (cached) return cached
  await listSessions({ includeAll: true })
  return cache?.engine === engine ? cache.sessions.get(sessionId) ?? null : null
}
