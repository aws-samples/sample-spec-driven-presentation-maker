// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The session catalog: on V3 both stores newest first, on V2 only V2's (kiro-cli never started
 * for it); filter first, then one row per id (the engine's own row over an imported store's, the
 * newer of two of one store); "Show all"; groups and recent cards; a store that cannot be read
 * leaves the others listed with `unavailable`; findSession from the last listing or a fresh one;
 * concurrent listings share one.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { StoredSession } from "./acp/engine"

const mocks = vi.hoisted(() => ({
  engine: "v3" as "v2" | "v3",
  stores: { v2: [] as StoredSession[], v3: [] as StoredSession[] },
  failing: new Set<string>(),
  connects: 0,
  listings: 0,
}))

vi.mock("./acp/engine-config", () => ({ readEngineConfig: () => ({ engine: mocks.engine, env: {} }) }))
vi.mock("./acp-process", () => ({
  withEngineConnection: async (_engine: string, fn: (connect: () => Promise<unknown>) => Promise<unknown>) => fn(async () => { mocks.connects++; return {} }),
}))
vi.mock("./acp/engine", () => {
  const adapter = (id: "v2" | "v3", openableBy: string[]) => ({
    id,
    sessionsOpenableBy: openableBy,
    listStoredSessions: async (ctx: { connect: () => Promise<unknown> }) => {
      mocks.listings++
      if (id === "v3") await ctx.connect()
      await new Promise((r) => setImmediate(r))
      if (mocks.failing.has(id)) throw new Error(`${id} store unreadable`)
      return mocks.stores[id]
    },
  })
  const adapters = [adapter("v2", ["v2", "v3"]), adapter("v3", ["v3"])]
  return { storedSessionAdapters: (engine: string) => adapters.filter((a) => a.sessionsOpenableBy.includes(engine)) }
})

const ago = (ms: number) => new Date(Date.now() - ms).toISOString()
const HOUR = 3_600_000

function session(sessionId: string, engine: "v2" | "v3", fields: Partial<StoredSession> = {}): StoredSession {
  return { sessionId, engine, title: sessionId, cwd: "/work/alpha", updatedAt: ago(HOUR), agentName: null, ...fields }
}

let catalog: typeof import("./kiro-sessions")

beforeEach(async () => {
  mocks.engine = "v3"
  mocks.stores = { v2: [], v3: [] }
  mocks.failing.clear()
  mocks.connects = 0
  mocks.listings = 0
  vi.resetModules()
  catalog = await import("./kiro-sessions")
})

afterEach(() => { vi.restoreAllMocks() })

const ids = (response: Awaited<ReturnType<typeof catalog.listSessions>>) => response.groups.flatMap((g) => g.sessions.map((s) => `${s.engine}:${s.sessionId}`))

describe("isCandidate", () => {
  it("accepts a user's session and refuses sub-agent, sdpm-agent and servers/local sessions", () => {
    expect(catalog.isCandidate({ cwd: "/work/project", agentName: "kiro_default" })).toBe(true)
    expect(catalog.isCandidate({ cwd: "/work/project", agentName: null, subagent: true })).toBe(false)
    expect(catalog.isCandidate({ cwd: "/work/project", agentName: "sdpm-orchestrator" })).toBe(false)
    expect(catalog.isCandidate({ cwd: "/work/repo/servers/local", agentName: null })).toBe(false)
    expect(catalog.isCandidate({ cwd: "/work/repo/servers/local/fixtures", agentName: null })).toBe(false)
  })
})

describe("listSessions", () => {
  it("on V3 lists both stores newest first, grouped by cwd, with the recent cards", async () => {
    mocks.stores.v3 = [session("sess_a", "v3", { updatedAt: ago(1000), cwd: "/work/alpha" }), session("sess_old", "v3", { updatedAt: ago(48 * HOUR), cwd: "/work/beta" })]
    mocks.stores.v2 = [session("u-b", "v2", { updatedAt: ago(2000), cwd: "/work/beta" }), session("u-c", "v2", { updatedAt: ago(3000), cwd: "/work/alpha" })]
    const result = await catalog.listSessions({ includeAll: false })
    expect(result.engine).toBe("v3")
    expect(result.unavailable).toBeUndefined()
    expect(result.groups.map((g) => [g.project, g.sessions.map((s) => s.sessionId)])).toEqual([["alpha", ["sess_a", "u-c"]], ["beta", ["u-b", "sess_old"]]])
    expect(result.recent.map((s) => s.sessionId)).toEqual(["sess_a", "u-b", "u-c"])
    expect(result.groups[0].sessions[0]).toMatchObject({ engine: "v3", project: "alpha" })
  })

  it("on V2 lists only V2's store, without kiro-cli", async () => {
    mocks.engine = "v2"
    mocks.stores.v3 = [session("sess_a", "v3")]
    mocks.stores.v2 = [session("u-b", "v2")]
    const result = await catalog.listSessions({ includeAll: false })
    expect(result.engine).toBe("v2")
    expect(ids(result)).toEqual(["v2:u-b"])
    expect(mocks.connects).toBe(0)
  })

  it("filters before it dedupes: V3's copy in servers/local does not hide the user's V2 row; a listed V3 row hides it", async () => {
    mocks.stores.v3 = [
      session("u-1", "v3", { cwd: "/repo/servers/local", updatedAt: ago(10) }),
      session("u-2", "v3", { cwd: "/work/alpha", updatedAt: ago(20) }),
    ]
    mocks.stores.v2 = [session("u-1", "v2", { updatedAt: ago(HOUR) }), session("u-2", "v2", { updatedAt: ago(HOUR) })]
    expect(ids(await catalog.listSessions({ includeAll: false }))).toEqual(["v3:u-2", "v2:u-1"])
    // Show all lists each id once too, as the user's row.
    const all = await catalog.listSessions({ includeAll: true })
    expect(ids(all)).toEqual(["v3:u-2", "v2:u-1"])
  })

  it("keeps the newer of two V3 rows of one session (imported into two workspaces)", async () => {
    mocks.stores.v3 = [session("u-1", "v3", { cwd: "/work/a", updatedAt: ago(HOUR) }), session("u-1", "v3", { cwd: "/work/b", updatedAt: ago(10) })]
    const result = await catalog.listSessions({ includeAll: false })
    expect(result.groups.map((g) => g.cwd)).toEqual(["/work/b"])
  })

  it("lists sdpm's own and sub-agent sessions only with Show all", async () => {
    mocks.stores.v3 = [session("sess_sdpm", "v3", { agentName: "sdpm-orchestrator" }), session("sess_user", "v3", { agentName: "vibe", updatedAt: ago(2 * HOUR) })]
    mocks.stores.v2 = [session("u-child", "v2", { subagent: true })]
    expect(ids(await catalog.listSessions({ includeAll: false }))).toEqual(["v3:sess_user"])
    const all = await catalog.listSessions({ includeAll: true })
    expect(ids(all).sort()).toEqual(["v2:u-child", "v3:sess_sdpm", "v3:sess_user"])
    expect(all.recent.map((s) => s.sessionId)).toEqual(["sess_user"])
  })

  it("lists V2's sessions with unavailable v3 when V3's store cannot be read", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {})
    mocks.failing.add("v3")
    mocks.stores.v2 = [session("u-b", "v2")]
    const result = await catalog.listSessions({ includeAll: false })
    expect(ids(result)).toEqual(["v2:u-b"])
    expect(result.unavailable).toEqual(["v3"])
  })

  it("shares one listing between concurrent requests", async () => {
    mocks.stores.v3 = [session("sess_a", "v3")]
    const [a, b] = await Promise.all([catalog.listSessions({ includeAll: false }), catalog.listSessions({ includeAll: true })])
    expect(ids(a)).toEqual(ids(b))
    expect(mocks.listings).toBe(2) // one per store
    await catalog.listSessions({ includeAll: false })
    expect(mocks.listings).toBe(4)
  })
})

describe("findSession", () => {
  it("finds a listed session from the last listing, else lists again", async () => {
    mocks.stores.v2 = [session("u-1", "v2", { title: "Source" })]
    await catalog.listSessions({ includeAll: false })
    mocks.stores.v2 = []
    expect(await catalog.findSession("u-1")).toMatchObject({ sessionId: "u-1", engine: "v2", title: "Source" })
    expect(mocks.listings).toBe(2)

    expect(await catalog.findSession("sess_new")).toBeNull()
    expect(mocks.listings).toBe(4)
    mocks.stores.v3 = [session("sess_new", "v3")]
    expect(await catalog.findSession("sess_new")).toMatchObject({ engine: "v3" })
  })

  it("prefers the user's row to sdpm's copy, and lists again after an engine switch", async () => {
    mocks.stores.v3 = [session("u-1", "v3", { cwd: "/repo/servers/local", updatedAt: ago(10) })]
    mocks.stores.v2 = [session("u-1", "v2", { cwd: "/work/alpha" })]
    expect(await catalog.findSession("u-1")).toMatchObject({ engine: "v2", cwd: "/work/alpha" })
    mocks.engine = "v2"
    mocks.stores.v2 = []
    expect(await catalog.findSession("u-1")).toBeNull()
  })
})
