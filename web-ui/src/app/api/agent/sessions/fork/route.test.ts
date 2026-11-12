// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * POST /api/agent/sessions/fork: looks the source up in the session catalog, forks it with the
 * configured engine in a kiro-cli registered under the fork's id, streams the phases, then
 * `done` with the fork's id and the origin (from the catalog, kept for the fork's first deck).
 * A fork kiro-cli could not read ends with `error` 502 (the fork was deleted by forkSession); a
 * source the catalog does not have ends with 404 and no fork; an invalid id is a 400 before
 * anything runs; a client that goes away after the fork exists gets it deleted.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

import { ForkNotReadError } from "@/lib/local/sessionErrors"

const SOURCE = { sessionId: "sess_src", engine: "v3", title: "earlier chat", cwd: "/workspace", updatedAt: "2026-11-05T00:00:00.000Z", agentName: "vibe" }

const mocks = vi.hoisted(() => ({
  forkSession: vi.fn(),
  discardForkedSession: vi.fn(),
  pendingOrigins: new Map<string, unknown>(),
  findSession: vi.fn(),
}))
vi.mock("@/lib/local/acp-process", () => ({
  forkSession: mocks.forkSession,
  discardForkedSession: mocks.discardForkedSession,
  pendingOrigins: mocks.pendingOrigins,
}))
vi.mock("@/lib/local/kiro-sessions", () => ({ findSession: mocks.findSession }))

import { POST } from "./route"

function fork(body: Record<string, unknown> = { sourceSessionId: "sess_src", clientSessionId: "C1" }, signal?: AbortSignal) {
  return POST(new Request("http://127.0.0.1:3000/api/agent/sessions/fork", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  }))
}

async function sse(res: Response): Promise<{ event: string; data: Record<string, unknown> }[]> {
  const text = await res.text()
  return text.split("\n\n").filter(Boolean).map((block) => {
    const lines = block.split("\n")
    return { event: lines[0].slice("event: ".length), data: JSON.parse(lines[1].slice("data: ".length)) }
  })
}

beforeEach(() => {
  for (const fn of [mocks.forkSession, mocks.discardForkedSession, mocks.findSession]) fn.mockReset()
  mocks.pendingOrigins.clear()
  mocks.findSession.mockResolvedValue(SOURCE)
  mocks.discardForkedSession.mockResolvedValue(undefined)
})

describe("POST /api/agent/sessions/fork", () => {
  it("forks the catalog's source and ends with done, the fork's id and the source's origin", async () => {
    mocks.forkSession.mockImplementation(async (_id: string, _agent: string, opts: { onPhase: (phase: string, detail?: unknown) => void }) => {
      opts.onPhase("starting")
      opts.onPhase("copying")
      opts.onPhase("loading", { replayed: 4 })
      return { ps: {}, sessionId: "sess_fork", outcome: "resumed" }
    })
    const events = await sse(await fork())
    expect(mocks.findSession).toHaveBeenCalledWith("sess_src")
    expect(mocks.forkSession).toHaveBeenCalledWith("sess_src", "sdpm-orchestrator", expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(events.map((e) => e.event)).toEqual(["phase", "phase", "phase", "done"])
    expect(events[2].data).toEqual({ phase: "loading", replayed: 4 })
    const done = events.at(-1)!.data as { sessionId: string; origin: Record<string, unknown> }
    expect(done.sessionId).toBe("sess_fork")
    expect(done.origin).toMatchObject({ sourceSessionId: "sess_src", title: "earlier chat", cwd: "/workspace", updatedAt: "2026-11-05T00:00:00.000Z" })
    expect(Date.parse(done.origin.forkedAt as string)).not.toBeNaN()
    expect(mocks.pendingOrigins.get("sess_fork")).toEqual(done.origin)
    expect(mocks.discardForkedSession).not.toHaveBeenCalled()
  })

  it("reports a fork kiro-cli could not read as 502", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      mocks.forkSession.mockRejectedValue(new ForkNotReadError())
      const events = await sse(await fork())
      expect(events.at(-1)).toEqual({ event: "error", data: { error: "kiro-cli could not read the forked session", code: 502 } })
      expect(mocks.pendingOrigins.size).toBe(0)
    } finally {
      warn.mockRestore()
    }
  })

  it("reports a source the catalog does not have as 404, without forking", async () => {
    mocks.findSession.mockResolvedValue(null)
    const events = await sse(await fork())
    expect(events).toEqual([{ event: "error", data: { error: "kiro session not found", code: 404 } }])
    expect(mocks.forkSession).not.toHaveBeenCalled()
  })

  it.each([["../escape"], ["a".repeat(129)], [42]])("refuses the source id %j with 400 before anything runs", async (sourceSessionId) => {
    const res = await fork({ sourceSessionId, clientSessionId: "C1" })
    expect(res.status).toBe(400)
    expect(mocks.findSession).not.toHaveBeenCalled()
    expect(mocks.forkSession).not.toHaveBeenCalled()
  })

  it("deletes a fork that exists when the client has gone", async () => {
    const controller = new AbortController()
    mocks.forkSession.mockImplementation(async () => {
      controller.abort()
      return { ps: {}, sessionId: "sess_fork", outcome: "resumed" }
    })
    const res = await fork(undefined, controller.signal)
    await res.text().catch(() => "")
    await vi.waitFor(() => expect(mocks.discardForkedSession).toHaveBeenCalledWith("sess_fork"))
    expect(mocks.pendingOrigins.size).toBe(0)
  })
})
