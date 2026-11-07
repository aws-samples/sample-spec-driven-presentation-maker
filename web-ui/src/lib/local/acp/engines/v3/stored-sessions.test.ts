// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V3's session store, read with session/list: workflow sessions left out, no cwd (every
 * workspace), the pages followed; each row is a V3 session with its mode as the agent; a row
 * without an id is dropped; without the list capability nothing is asked.
 */

import { describe, expect, it, vi } from "vitest"

import type { EngineCapabilities, StoreContext } from "../../engine"
import { v3Adapter } from "."

const CAPS = (list: boolean): EngineCapabilities => ({
  session: { list, close: true, delete: true, fork: true }, replayMarking: true, extensionMethods: new Set(), steer: true,
})

function store(pages: unknown[], list = true) {
  const calls: Record<string, unknown>[] = []
  const request = vi.fn(async (_method: string, params?: Record<string, unknown>) => {
    calls.push(params ?? {})
    return pages[calls.length - 1]
  })
  const ctx: StoreContext = { env: {} as NodeJS.ProcessEnv, connect: async () => ({ request, caps: CAPS(list) }) }
  return { ctx, request, calls }
}

describe("V3 stored sessions", () => {
  it("lists every workspace's sessions without workflow sessions, as V3 rows", async () => {
    const { ctx, request } = store([{ sessions: [
      { sessionId: "sess_1", cwd: "/home/user/proj", title: "Remember MANGO", updatedAt: "2026-11-07T11:42:29.006Z", _meta: { kiro: { agentMode: "vibe", createdAt: "2026-11-07T11:42:25.155Z", status: "idle" } } },
      { sessionId: "ad46389c-6f86-48b2-a234-ebb9b023bd11", cwd: "/workspace/sdpm/servers/local", updatedAt: "2026-11-07T11:00:00Z" },
      { cwd: "/nowhere", title: "no id" },
    ] }])
    expect(await v3Adapter.listStoredSessions(ctx)).toEqual([
      { sessionId: "sess_1", engine: "v3", title: "Remember MANGO", cwd: "/home/user/proj", updatedAt: "2026-11-07T11:42:29.006Z", agentName: "vibe" },
      { sessionId: "ad46389c-6f86-48b2-a234-ebb9b023bd11", engine: "v3", title: "", cwd: "/workspace/sdpm/servers/local", updatedAt: "2026-11-07T11:00:00Z", agentName: null },
    ])
    expect(request).toHaveBeenCalledWith("session/list", { _meta: { kiro: { filter: { workflowSessions: "exclude" } } } }, expect.objectContaining({ timeoutMs: expect.any(Number) }))
    expect(v3Adapter.sessionsOpenableBy).toEqual(["v3"])
  })

  it("follows nextCursor", async () => {
    const { ctx, calls } = store([
      { sessions: [{ sessionId: "sess_1", cwd: "/a" }], nextCursor: "c2" },
      { sessions: [{ sessionId: "sess_2", cwd: "/b" }] },
    ])
    expect((await v3Adapter.listStoredSessions(ctx)).map((s) => s.sessionId)).toEqual(["sess_1", "sess_2"])
    expect(calls[1]).toMatchObject({ cursor: "c2" })
  })

  it("asks nothing when kiro-cli does not advertise session/list", async () => {
    const { ctx, request } = store([], false)
    expect(await v3Adapter.listStoredSessions(ctx)).toEqual([])
    expect(request).not.toHaveBeenCalled()
  })
})
