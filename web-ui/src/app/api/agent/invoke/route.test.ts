// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * POST /api/agent/invoke answers a session conflict with 409 and a code the chat UI
 * translates: `session_busy` while the session is still answering, `session_locked` when
 * kiro-cli refuses to load a session another process holds. A kiro-cli that does not answer
 * its setup requests in time gets 504 `agent_timeout`; one that cannot be made ready gets 502
 * with its start-up code. Other failures still throw.
 *
 * A reopened deck is opened by the process manager (openDeckSession, with the id its `.session`
 * names); a `created` outcome (no `.session`, or kiro-cli no longer has it) runs the turn as the
 * session's first prompt, which names the deck (`Current deck: <dir>`); only a saved session
 * kiro-cli lost opens the stream with the `context_not_carried_over` notice (a deck an MCP client
 * made has no `.session` and gets none), a resumed session that also ran on the other engine with `context_from_other_engine`. A fork's
 * first message after its process was evicted reopens the copy (openForkedSession); a copy
 * kiro-cli could not read gets the notice instead of failing. Stop while the chat starts answers a
 * stream that ends at once (no data); a client that went away gets 499. A new chat whose client id had a
 * chat that was released or whose kiro-cli exited reopens its kiro session (createNewProcessFor):
 * `resumed` runs the turn as a later prompt, a session kiro-cli no longer has as a first prompt
 * with the notice. The route hands the notice and the user's own text to sendPrompt (the chat
 * buffers the notice after the turn's `turn` event), replays the period from that turn's first
 * event, and saves nothing itself.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import type { BufferedEvent } from "@/lib/local/conversation/events"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"
import type { LocalSessionNoticeCode } from "@/lib/local/sessionNotices"
import { SessionBusyError, SessionLockedError } from "@/lib/local/sessionErrors"
import { AgentStartError, AgentTimeoutError, type AgentStartErrorCode } from "@/lib/local/turnErrors"

const acp = vi.hoisted(() => ({
  beginStart: vi.fn(),
  hasProcess: vi.fn(),
  openDeckSession: vi.fn(),
  openForkedSession: vi.fn(),
  createNewProcessFor: vi.fn(),
  sendPrompt: vi.fn(),
  getBufferedEvents: vi.fn(),
  readSessionFromDeck: vi.fn(),
}))
vi.mock("@/lib/local/acp-process", () => ({
  ...acp,
  pendingOrigins: new Map(),
}))
const resolveDeckDir = vi.hoisted(() => vi.fn((id: string): string | null => `/home/u/Documents/SDPM-Presentations/${id}`))
vi.mock("@/lib/local/deck-paths", () => ({ resolveDeckDir }))

import { POST } from "./route"

const ORIGIN: SessionOrigin = { sourceSessionId: "SRC", title: "earlier chat", cwd: "/workspace", updatedAt: "2026-11-05T00:00:00.000Z", forkedAt: "2026-11-06T00:00:00.000Z" }

function invoke(body: Record<string, unknown>) {
  return POST(new Request("http://127.0.0.1:3000/api/agent/invoke", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: "hi", mode: "vibe", ...body }),
  }))
}

/** The start the route registers: its signal follows the request and `stop()` (Stop for the session). */
let stopStart: () => void

beforeEach(() => {
  for (const fn of Object.values(acp)) fn.mockReset()
  acp.beginStart.mockImplementation((_clientId: string, outer: AbortSignal) => {
    const controller = new AbortController()
    let stopped = false
    outer.addEventListener("abort", () => controller.abort(), { once: true })
    stopStart = () => { stopped = true; controller.abort() }
    return { signal: controller.signal, stoppedByUser: () => stopped, end: vi.fn() }
  })
})

describe("POST /api/agent/invoke session conflicts and start-up failures", () => {
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
    acp.openDeckSession.mockRejectedValue(new SessionLockedError("Session is active in another process (PID 4242)"))
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

  it.each<AgentStartErrorCode>(["agent_start_failed", "agent_auth_required", "agent_definition_rejected", "mcp_failed"])(
    "returns 502 %s when kiro-cli cannot be made ready",
    async (code) => {
      acp.hasProcess.mockReturnValue(false)
      acp.createNewProcessFor.mockRejectedValue(new AgentStartError(code, "details for the log"))
      const res = await invoke({ sessionId: "C1" })
      expect(res.status).toBe(502)
      const body = await res.json()
      expect(body).toMatchObject({ code, error: expect.any(String) })
      expect(body.error).not.toContain("details for the log")
    },
  )

  it("rethrows failures that are not session conflicts", async () => {
    acp.hasProcess.mockReturnValue(false)
    acp.createNewProcessFor.mockRejectedValue(new Error("unexpected"))
    await expect(invoke({ sessionId: "C1" })).rejects.toThrow(/unexpected/)
  })
})

/**
 * sendPrompt for a turn that ends at once, so the SSE body can be read to the end. Like the
 * chat, it buffers the notice it is given among the turn's first events.
 */
function promptEndingAt(sessionId: string) {
  return (_clientId: string, _text: string, opts: { notice?: LocalSessionNoticeCode } = {}) => {
    const buffered: BufferedEvent[] = opts.notice ? [{ id: 1, event: { kind: "data", payload: { notice: { code: opts.notice } } } }] : []
    acp.getBufferedEvents.mockReturnValue(buffered)
    let listener: ((entry: BufferedEvent) => void) | null = null
    return Promise.resolve({
      sessionId,
      replayFrom: 1,
      subscribe: (fn: (entry: BufferedEvent) => void) => { listener = fn; return () => { listener = null } },
      send: () => listener?.({ id: buffered.length + 1, event: { kind: "end", stopReason: "end_turn" } }),
    })
  }
}

async function events(res: Response): Promise<Record<string, unknown>[]> {
  const text = await res.text()
  return text.split("\n").filter((l) => l.startsWith("data: ")).map((l) => JSON.parse(l.slice(6)))
}

const DECK_FALLBACK_ID = "mcp-made-deck".padEnd(36, "0")

describe("POST /api/agent/invoke on a reopened deck", () => {
  beforeEach(() => acp.hasProcess.mockReturnValue(false))

  it("opens the kiro session named in .session, under the client's id, without a notice", async () => {
    acp.readSessionFromDeck.mockReturnValue("K1")
    acp.openDeckSession.mockResolvedValue({ chat: {}, outcome: "resumed", otherEngine: false })
    acp.sendPrompt.mockImplementation(promptEndingAt("K1"))
    const res = await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(res.status).toBe(200)
    expect(acp.openDeckSession).toHaveBeenCalledWith(DECK_FALLBACK_ID, "mcp-made-deck", "K1", "sdpm-orchestrator", { signal: expect.any(AbortSignal) })
    expect(acp.createNewProcessFor).not.toHaveBeenCalled()
    expect(acp.sendPrompt).toHaveBeenCalledWith(DECK_FALLBACK_ID, "hi", { notice: undefined, displayText: "hi", signal: expect.any(AbortSignal) })
    expect(acp.getBufferedEvents).toHaveBeenCalledWith(DECK_FALLBACK_ID, 0)
    expect((await events(res)).some((e) => "notice" in e)).toBe(false)
  })

  it("runs a deck's first prompt in a new session without a notice when it has no .session", async () => {
    acp.readSessionFromDeck.mockReturnValue(null)
    acp.openDeckSession.mockResolvedValue({ chat: {}, outcome: "created", otherEngine: false })
    acp.sendPrompt.mockImplementation(promptEndingAt("NEW1"))
    const res = await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(res.status).toBe(200)
    expect(acp.openDeckSession).toHaveBeenCalledWith(DECK_FALLBACK_ID, "mcp-made-deck", null, "sdpm-orchestrator", { signal: expect.any(AbortSignal) })
    // A new session's first prompt carries the interaction mode and the deck's directory.
    expect(resolveDeckDir).toHaveBeenCalledWith("mcp-made-deck")
    expect(acp.sendPrompt).toHaveBeenCalledWith(
      DECK_FALLBACK_ID,
      "Interaction mode: fast\n\nCurrent deck: /home/u/Documents/SDPM-Presentations/mcp-made-deck\n\nhi",
      { notice: undefined, displayText: "hi", signal: expect.any(AbortSignal) },
    )
    expect((await events(res)).some((e) => "notice" in e)).toBe(false)
  })

  it("runs a created session's first prompt with the notice first when kiro-cli lost the saved one", async () => {
    acp.readSessionFromDeck.mockReturnValue("GONE")
    acp.openDeckSession.mockResolvedValue({ chat: {}, outcome: "created", otherEngine: false })
    acp.sendPrompt.mockImplementation(promptEndingAt("NEW1"))
    const res = await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(res.status).toBe(200)
    expect(acp.openDeckSession).toHaveBeenCalledWith(DECK_FALLBACK_ID, "mcp-made-deck", "GONE", "sdpm-orchestrator", { signal: expect.any(AbortSignal) })
    expect(acp.readSessionFromDeck).toHaveBeenCalledTimes(1)
    expect(acp.sendPrompt).toHaveBeenCalledWith(
      DECK_FALLBACK_ID,
      "Interaction mode: fast\n\nCurrent deck: /home/u/Documents/SDPM-Presentations/mcp-made-deck\n\nhi",
      { notice: "context_not_carried_over", displayText: "hi", signal: expect.any(AbortSignal) },
    )
    expect((await events(res))[0]).toEqual({ notice: { code: "context_not_carried_over" } })
  })

  it("leaves the deck line out when the deck directory does not resolve", async () => {
    acp.readSessionFromDeck.mockReturnValue(null)
    acp.openDeckSession.mockResolvedValue({ chat: {}, outcome: "created", otherEngine: false })
    acp.sendPrompt.mockImplementation(promptEndingAt("NEW1"))
    resolveDeckDir.mockReturnValueOnce(null)
    await invoke({ sessionId: DECK_FALLBACK_ID, deckId: "mcp-made-deck" })
    expect(acp.sendPrompt).toHaveBeenCalledWith(DECK_FALLBACK_ID, "Interaction mode: fast\n\nhi", { notice: undefined, displayText: "hi", signal: expect.any(AbortSignal) })
  })

  it("says so when the deck's session also ran on the other engine", async () => {
    acp.readSessionFromDeck.mockReturnValue("K1")
    acp.openDeckSession.mockResolvedValue({ chat: {}, outcome: "resumed", otherEngine: true })
    acp.sendPrompt.mockImplementation(promptEndingAt("K1"))
    const res = await invoke({ sessionId: "C1", deckId: "d1" })
    expect(acp.sendPrompt).toHaveBeenCalledWith("C1", "hi", { notice: "context_from_other_engine", displayText: "hi", signal: expect.any(AbortSignal) })
    expect((await events(res))[0]).toEqual({ notice: { code: "context_from_other_engine" } })
  })
})

describe("POST /api/agent/invoke on a forked chat", () => {
  beforeEach(() => acp.hasProcess.mockReturnValue(false))

  it("reopens the copy of an evicted fork, with the continuation in the first prompt", async () => {
    acp.openForkedSession.mockResolvedValue({ chat: {}, outcome: "resumed" })
    acp.sendPrompt.mockImplementation(promptEndingAt("F1"))
    const res = await invoke({ sessionId: "F1", continuedFrom: ORIGIN })
    expect(res.status).toBe(200)
    expect(acp.openForkedSession).toHaveBeenCalledWith("F1", "sdpm-orchestrator", { signal: expect.any(AbortSignal) })
    expect(acp.sendPrompt.mock.calls[0][2]).toEqual({ notice: undefined, displayText: "hi", signal: expect.any(AbortSignal) })
    expect(acp.sendPrompt.mock.calls[0][1]).toContain("hi")
  })

  it("goes on with the notice when kiro-cli could not read the copy", async () => {
    acp.openForkedSession.mockResolvedValue({ chat: {}, outcome: "created" })
    acp.sendPrompt.mockImplementation(promptEndingAt("F1"))
    const res = await invoke({ sessionId: "F1", continuedFrom: ORIGIN })
    expect(res.status).toBe(200)
    expect(acp.sendPrompt.mock.calls[0][2]).toEqual({ notice: "context_not_carried_over", displayText: "hi", signal: expect.any(AbortSignal) })
    expect((await events(res))[0]).toEqual({ notice: { code: "context_not_carried_over" } })
  })
})

describe("POST /api/agent/invoke for a chat whose kiro-cli is gone", () => {
  beforeEach(() => acp.hasProcess.mockReturnValue(false))

  it("runs a reopened session's prompt as a later one, without a notice", async () => {
    acp.createNewProcessFor.mockResolvedValue({ chat: {}, resumed: true })
    acp.sendPrompt.mockImplementation(promptEndingAt("K1"))
    const res = await invoke({ sessionId: "C1" })
    expect(res.status).toBe(200)
    expect(acp.sendPrompt).toHaveBeenCalledWith("C1", "hi", { notice: undefined, displayText: "hi", signal: expect.any(AbortSignal) })
  })

  it("runs a session kiro-cli no longer has as a first prompt, with the notice", async () => {
    acp.createNewProcessFor.mockResolvedValue({ chat: {}, resumed: false, notice: "context_not_carried_over" })
    acp.sendPrompt.mockImplementation(promptEndingAt("K2"))
    const res = await invoke({ sessionId: "C1" })
    expect(acp.sendPrompt).toHaveBeenCalledWith("C1", "Interaction mode: fast\n\nhi", { notice: "context_not_carried_over", displayText: "hi", signal: expect.any(AbortSignal) })
    expect((await events(res))[0]).toEqual({ notice: { code: "context_not_carried_over" } })
  })

  it("runs a new chat's prompt as its first", async () => {
    acp.createNewProcessFor.mockResolvedValue({ chat: {}, resumed: false })
    acp.sendPrompt.mockImplementation(promptEndingAt("K3"))
    await invoke({ sessionId: "C1" })
    expect(acp.sendPrompt).toHaveBeenCalledWith("C1", "Interaction mode: fast\n\nhi", { notice: undefined, displayText: "hi", signal: expect.any(AbortSignal) })
  })
})

describe("POST /api/agent/invoke stopped while its chat starts", () => {
  beforeEach(() => acp.hasProcess.mockReturnValue(false))

  /** createNewProcessFor that waits for its signal, as the pool does, and rejects with AbortError. */
  function startUntilAborted() {
    acp.createNewProcessFor.mockImplementation((_id: string, _agent: string, opts: { signal: AbortSignal }) => new Promise((_, reject) => {
      opts.signal.addEventListener("abort", () => reject(new DOMException("Request cancelled", "AbortError")), { once: true })
    }))
  }

  it("answers 200 with a stream that ends at once, and sends no prompt", async () => {
    startUntilAborted()
    const pending = invoke({ sessionId: "C1" })
    await new Promise((r) => setImmediate(r))
    stopStart()
    const res = await pending
    expect(res.status).toBe(200)
    expect(res.headers.get("content-type")).toBe("text/event-stream")
    expect(await res.text()).toBe("")
    expect(acp.sendPrompt).not.toHaveBeenCalled()
  })

  it("answers 499 when the client went away", async () => {
    startUntilAborted()
    const controller = new AbortController()
    const pending = POST(new Request("http://127.0.0.1:3000/api/agent/invoke", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "hi", mode: "vibe", sessionId: "C1" }),
      signal: controller.signal,
    }))
    await new Promise((r) => setImmediate(r))
    controller.abort()
    expect((await pending).status).toBe(499)
  })
})
