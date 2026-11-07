// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * POST /api/agent/sessions/fork: copies the kiro session, opens the copy in a kiro-cli under the
 * fork's id and streams the phases, then `done` with the fork's id and origin (kept for the
 * fork's first deck). A copy kiro-cli could not read (it started an empty session: `created`)
 * fails the fork: its process is ended, the copy removed, and the stream ends with `error`
 * (code 502), so the chat does not continue "from" a session without its history.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"

const ORIGIN: SessionOrigin = { sourceSessionId: "SRC", title: "earlier chat", cwd: "/workspace", updatedAt: "2026-11-05T00:00:00.000Z", forkedAt: "2026-11-06T00:00:00.000Z" }

const mocks = vi.hoisted(() => ({
  openForkedSession: vi.fn(),
  terminateProcess: vi.fn(),
  pendingOrigins: new Map<string, unknown>(),
  forkSession: vi.fn(),
  removeForkedSession: vi.fn(),
}))
vi.mock("@/lib/local/acp-process", () => ({
  openForkedSession: mocks.openForkedSession,
  terminateProcess: mocks.terminateProcess,
  pendingOrigins: mocks.pendingOrigins,
}))
vi.mock("@/lib/local/kiro-sessions", () => ({ forkSession: mocks.forkSession, removeForkedSession: mocks.removeForkedSession }))

import { POST } from "./route"

function fork() {
  return POST(new Request("http://127.0.0.1:3000/api/agent/sessions/fork", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sourceSessionId: "SRC", clientSessionId: "C1" }),
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
  for (const fn of [mocks.openForkedSession, mocks.terminateProcess, mocks.forkSession, mocks.removeForkedSession]) fn.mockReset()
  mocks.pendingOrigins.clear()
  mocks.forkSession.mockResolvedValue({ newId: "F1", origin: ORIGIN })
  mocks.removeForkedSession.mockResolvedValue(undefined)
})

describe("POST /api/agent/sessions/fork", () => {
  it("opens the copy under the fork's id and ends with done", async () => {
    mocks.openForkedSession.mockImplementation(async (_id: string, _agent: string, opts: { onPhase: (phase: string) => void }) => {
      opts.onPhase("starting")
      return { ps: {}, outcome: "resumed" }
    })
    const events = await sse(await fork())
    expect(mocks.openForkedSession).toHaveBeenCalledWith("F1", "sdpm-orchestrator", expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(events.map((e) => e.event)).toEqual(["phase", "phase", "done"])
    expect(events.at(-1)!.data).toEqual({ sessionId: "F1", origin: ORIGIN })
    expect(mocks.pendingOrigins.get("F1")).toEqual(ORIGIN)
    expect(mocks.terminateProcess).not.toHaveBeenCalled()
  })

  it("fails a fork whose copy kiro-cli could not read: ends its process, removes the copy and reports 502", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      mocks.openForkedSession.mockResolvedValue({ ps: {}, outcome: "created" })
      const events = await sse(await fork())
      expect(events.at(-1)).toEqual({ event: "error", data: { error: "kiro-cli could not read the copied session", code: 502 } })
      expect(mocks.terminateProcess).toHaveBeenCalledWith("F1")
      expect(mocks.removeForkedSession).toHaveBeenCalledWith("F1")
      expect(mocks.pendingOrigins.has("F1")).toBe(false)
    } finally {
      warn.mockRestore()
    }
  })
})
