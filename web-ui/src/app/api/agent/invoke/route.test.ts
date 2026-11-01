// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * POST /api/agent/invoke answers a session conflict with 409 and a code the chat UI
 * translates: `session_busy` while the session is still answering, `session_locked` when
 * kiro-cli refuses to load a session another process holds. Other failures still throw.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { SessionBusyError } from "@/lib/local/sessionErrors"

const acp = vi.hoisted(() => ({
  hasProcess: vi.fn(),
  getOrCreateProcess: vi.fn(),
  createNewProcessFor: vi.fn(),
  sendPrompt: vi.fn(),
}))
vi.mock("@/lib/local/acp-process", () => ({
  ...acp,
  pendingOrigins: new Map(),
  saveOriginToDeck: vi.fn(),
  saveSessionToDeck: vi.fn(),
}))

import { POST } from "./route"

const LOCK_ERROR = "Internal error: Failed to start session: Session is active in another process (PID 4242)"

function invoke(body: Record<string, unknown>) {
  return POST(new Request("http://127.0.0.1:3000/api/agent/invoke", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: "hi", mode: "vibe", ...body }),
  }))
}

beforeEach(() => {
  for (const fn of Object.values(acp)) fn.mockReset()
})

describe("POST /api/agent/invoke session conflicts", () => {
  it("returns 409 session_busy while the session is still answering", async () => {
    acp.hasProcess.mockReturnValue(true)
    acp.sendPrompt.mockRejectedValue(new SessionBusyError())
    const res = await invoke({ sessionId: "K1", deckId: "d1" })
    expect(res.status).toBe(409)
    expect(await res.json()).toMatchObject({ code: "session_busy", error: expect.stringMatching(/still answering/) })
  })

  it("returns 409 session_locked when another process holds the session", async () => {
    acp.hasProcess.mockReturnValue(false)
    acp.getOrCreateProcess.mockRejectedValue(new Error(LOCK_ERROR))
    const res = await invoke({ sessionId: "K1", deckId: "d1" })
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.code).toBe("session_locked")
    expect(body.error).toContain("another kiro-cli process")
    expect(acp.sendPrompt).not.toHaveBeenCalled()
  })

  it("rethrows failures that are not session conflicts", async () => {
    acp.hasProcess.mockReturnValue(false)
    acp.createNewProcessFor.mockRejectedValue(new Error("spawn kiro-cli ENOENT"))
    await expect(invoke({ sessionId: "C1" })).rejects.toThrow(/ENOENT/)
  })
})
