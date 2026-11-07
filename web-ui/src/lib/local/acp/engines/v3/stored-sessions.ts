// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V3's session store, read through kiro-cli: `session/list` without a `cwd` lists the sessions
 * of every workspace (kiro-cli 3.1.0; `listScope: "user"` is the remote scope and lists none
 * locally), with the sessions of kiro workflows left out. A V2 session V3 imported appears here
 * under its V2 id, once per workspace it was imported into.
 */
import type { StoreContext, StoredSession } from "../../engine"
import type { ListSessionsResponse, SessionInfo } from "../../schema"
import type { V3ListSessionsMeta, V3SessionInfoMeta } from "./types"

/** A bound on session/list's pages (kiro-cli 3.1.0 answers one page). */
const MAX_PAGES = 20
/** session/list answers in well under a second (it reads kiro-cli's local store). */
const LIST_TIMEOUT_MS = 15_000

function row(info: SessionInfo): StoredSession | null {
  if (typeof info?.sessionId !== "string" || !info.sessionId) return null
  const kiro = ((info._meta as { kiro?: V3SessionInfoMeta } | null | undefined)?.kiro) ?? {}
  return {
    sessionId: info.sessionId,
    engine: "v3",
    title: typeof info.title === "string" ? info.title : "",
    cwd: typeof info.cwd === "string" ? info.cwd : "",
    updatedAt: typeof info.updatedAt === "string" ? info.updatedAt : "",
    agentName: kiro.agentMode ?? kiro.modeId ?? null,
  }
}

/** Every session V3 lists; none when kiro-cli does not advertise session/list. */
export async function listV3Sessions(ctx: StoreContext): Promise<StoredSession[]> {
  const { request, caps } = await ctx.connect()
  if (!caps.session.list) return []
  const meta: V3ListSessionsMeta = { kiro: { filter: { workflowSessions: "exclude" } } }
  const sessions: StoredSession[] = []
  let cursor: string | null = null
  for (let page = 0; page < MAX_PAGES; page++) {
    const answer = await request("session/list", { ...(cursor ? { cursor } : {}), _meta: meta }, { timeoutMs: LIST_TIMEOUT_MS }) as ListSessionsResponse | undefined
    for (const info of Array.isArray(answer?.sessions) ? answer.sessions : []) {
      const session = row(info)
      if (session) sessions.push(session)
    }
    cursor = typeof answer?.nextCursor === "string" && answer.nextCursor ? answer.nextCursor : null
    if (!cursor) return sessions
  }
  console.warn("[acp] V3 session/list: stopped after %d pages", MAX_PAGES)
  return sessions
}
