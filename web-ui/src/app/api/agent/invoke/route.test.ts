// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * POST /api/agent/invoke answers a session conflict with 409 and a code the chat UI
 * translates: `session_busy` while the session is still answering, `session_locked` when
 * kiro-cli refuses to load a session another process holds. A kiro-cli that does not answer
 * its setup requests in time gets 504 `agent_timeout`. Other failures still throw.
 *
 * A reopened deck restores the kiro session its `.session` names; with none to load (no
 * `.session`, or kiro-cli no longer has it) the turn runs in a new session, saved to `.session`,
 * and the stream opens with the `context_not_carried_over` notice.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { SessionBusyError } from "@/lib/local/sessionErrors"
import { AgentTimeoutError } from "@/lib/local/turnErrors"

const acp = vi.hoisted(() => ({
  hasProcess: vi.fn(),
  getOrCreateProcess: vi.fn(),
  createNewProcessFor: vi.fn(),
  sendPrompt: vi.fn(),
  readSessionFromDeck: vi.fn(),
  saveSessionToDeck: vi.fn(),
}))
vi.mock("@/lib/local/acp-process", () => ({
  ...acp,
  pendingOrigins: new Map(),
  saveOriginToDeck: vi.fn(),
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
    acp.readSessionFromDeck.mockReturnValue("K1")
    acp.getOrCreateProcess.mockRejectedValue(new Error(LOCK_ERROR))
    const res = await invoke({ sessionId: "K1", deckId: "d1" })
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.code).toBe("session_locked")
    expect(body.error).toContain("another kiro-cli process")
    expect(acp.sendPrompt).not.toHaveBeenCalled()
  })

  it("returns 504 agent_timeout when kiro-cli does not answer its setup requests", async () => {
    acp.hasProcess.mockReturnValue(false)
    acp.createNewProcessFor.mockRejectedValue(new AgentTimeoutError("initialize", 30_000))
    const res = await invoke({ sessionId: "C1" })
    expect(res.status).toBe(504)
    expect(await res.json()).toMatchObject({ status: "error", code: "agent_timeout" })
    expect(acp.createNewProcessFor).toHaveBeenCalledWith("C1", "sdpm-orchestrator", { signal: expect.any(AbortSignal) })
  })

  it("rethrows failures that are not session conflicts", async () => {
    acp.hasProcess.mockReturnValue(false)
    acp.createNewProcessFor.mockRejectedValue(new Error("spawn kiro-cli ENOENT"))
    await expect(invoke({ sessionId: "C1" })).rejects.toThrow(/ENOENT/)
  })
})

/** A prompt whose turn ends at once, so the SSE body can be read to the end. */
function promptEndingAt(sessionId: string) {
  let listener: ((msg: Record<string, unknown>) => void) | null = null
  return {
    sessionId,
    subscribe: (fn: (msg: Record<string, unknown>) => void) => { listener = fn; return () => { listener = null } },
    send: () => listener?.({ method: "_sdpm/turn_end", params: { sessionId, stopReason: "end_turn" } }),
  }
}

async function events(res: Response): Promise<Record<string, unknown>[]> {
  const text = await res.text()
  return text.split("\n").filter((l) => l.startsWith("data: ")).map((l) => JSON.parse(l.slice(6)))
}

const DECK_FALLBACK_ID = "mcp-made-deck".padEnd(36, "0")
const NOT_FOUND_ERROR = `Internal error: Failed to start session: Session not found: ${DECK_FALLBACK_ID}`

describe("POST /api/agent/invoke on a reopened deck", () => {
  beforeEach(() => acp.hasProcess.mockReturnValue(false))

  it("restores the kiro session named in .session, under the client's id", async () => {
    acp.readSessionFromDeck.mockReturnValue("K1")
    acp.sendPrompt.mockResolvedValue(promptEndingAt("K1"))
    const res = await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(res.status).toBe(200)
    expect(acp.getOrCreateProcess).toHaveBeenCalledWith(DECK_FALLBACK_ID, "sdpm-orchestrator", { signal: expect.any(AbortSignal), kiroSessionId: "K1" })
    expect(acp.createNewProcessFor).not.toHaveBeenCalled()
    expect(acp.saveSessionToDeck).not.toHaveBeenCalled()
    expect(acp.sendPrompt).toHaveBeenCalledWith(DECK_FALLBACK_ID, "hi", "sdpm-orchestrator")
    expect((await events(res)).some((e) => "notice" in e)).toBe(false)
  })

  it("starts a new session for a deck without .session, saves it and sends the notice first", async () => {
    acp.readSessionFromDeck.mockReturnValue(null)
    acp.createNewProcessFor.mockResolvedValue({ sessionId: "NEW1" })
    acp.sendPrompt.mockResolvedValue(promptEndingAt("NEW1"))
    const res = await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(res.status).toBe(200)
    expect(acp.getOrCreateProcess).not.toHaveBeenCalled()
    expect(acp.createNewProcessFor).toHaveBeenCalledWith(DECK_FALLBACK_ID, "sdpm-orchestrator", { signal: expect.any(AbortSignal) })
    expect(acp.saveSessionToDeck).toHaveBeenCalledWith("mcp-made-deck", "NEW1")
    // A new session's first prompt carries the interaction mode.
    expect(acp.sendPrompt).toHaveBeenCalledWith(DECK_FALLBACK_ID, "Interaction mode: fast\n\nhi", "sdpm-orchestrator")
    expect((await events(res))[0]).toEqual({ notice: { code: "context_not_carried_over" } })
  })

  it("starts a new session when kiro-cli no longer has the saved one", async () => {
    acp.readSessionFromDeck.mockReturnValue(DECK_FALLBACK_ID)
    acp.getOrCreateProcess.mockRejectedValue(new Error(NOT_FOUND_ERROR))
    acp.createNewProcessFor.mockResolvedValue({ sessionId: "NEW2" })
    acp.sendPrompt.mockResolvedValue(promptEndingAt("NEW2"))
    const res = await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(res.status).toBe(200)
    expect(acp.saveSessionToDeck).toHaveBeenCalledWith("mcp-made-deck", "NEW2")
    expect((await events(res))[0]).toEqual({ notice: { code: "context_not_carried_over" } })
  })
})
