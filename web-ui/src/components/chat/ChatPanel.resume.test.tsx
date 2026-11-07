// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel resume (Cloud, R3): a deck whose session was working when the page last saw it
 * follows the session after the history load — the history is cut at the work's opening
 * prompt and the replay rebuilds it. An idle session opens no connection; Local is unchanged.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { deckSessionId } from "@/lib/sessionId"

const mode = vi.hoisted(() => ({ local: false }))
const { invokeAgentCore, resumeAgentCore, cancelAgentCore, getChatHistory } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(),
  resumeAgentCore: vi.fn(),
  cancelAgentCore: vi.fn(),
  getChatHistory: vi.fn(),
}))

vi.mock("@/lib/mode", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/mode")>()),
  get IS_LOCAL() { return mode.local },
}))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { id_token: "tok", access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn(), info: vi.fn(), error: vi.fn() }) }))
vi.mock("@/lib/runtimeConfig", () => ({
  loadRuntimeConfig: vi.fn(async () => ({ agentRuntimeArn: "arn:test", awsRegion: "us-east-1" })),
}))
vi.mock("@/services/agentCoreService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/agentCoreService")>()),
  setAgentConfig: vi.fn(),
  stopRuntimeSession: vi.fn(),
  prepareAgentCore: vi.fn(async () => undefined),
  invokeAgentCore,
  resumeAgentCore,
  cancelAgentCore,
}))
vi.mock("@/services/deckService", () => ({
  getChatHistory,
  patchDeck: vi.fn(),
  createReview: vi.fn(),
  batchGetSlidePreviewUrls: vi.fn(async () => new Map()),
  fetchStyles: vi.fn(async () => []),
  fetchTemplates: vi.fn(async () => []),
}))
vi.mock("@/services/localService", () => ({
  saveLocalChat: vi.fn(async () => undefined),
  localStreamUrl: vi.fn(() => null),
  hasLocalStream: vi.fn(async () => false),
  stopLocalAgent: vi.fn(async () => undefined),
  getLocalSessionModels: vi.fn(async () => null),
  setLocalSessionModel: vi.fn(async () => null),
}))
vi.mock("@/services/kiroSessionsService", () => ({ forkKiroSession: vi.fn(), listKiroSessions: vi.fn(async () => ({ recent: [] })) }))

import { ChatPanel } from "./ChatPanel"

const SESSION = deckSessionId("u1", "d1")
const HISTORY = [
  { role: "user", content: [{ text: "earlier" }] },
  { role: "assistant", content: [{ text: "earlier reply" }] },
  { role: "user", content: [{ text: "make it" }] },
  { role: "assistant", content: [{ text: "stale partial" }] },
]

type ResumeHandlers = {
  onResumeAck: (ack: { working: boolean }) => void
  onStreamUpdate: (text: string) => void
  onToolUse: (name: string, data: Record<string, unknown>) => void
  onSession: { onEvent: (ev: Record<string, unknown>, info: { own: boolean }) => void }
}

function storeState(sessionId: string, state: "working" | "idle") {
  localStorage.setItem(`sdpm-session:${sessionId}`, JSON.stringify({ state, lastSeq: 7, at: Date.now() }))
}

/** resumeAgentCore that replays the start of a working period; returns live controls. */
function workingResume() {
  const live: { handlers?: ResumeHandlers; finish?: () => void } = {}
  resumeAgentCore.mockImplementationOnce((_sid: string, _tok: string, _from: number, h: ResumeHandlers) => {
    live.handlers = h
    h.onResumeAck({ working: true })
    h.onSession.onEvent({ work: { state: "busy" } }, { own: false })
    h.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: false })
    h.onStreamUpdate("Hel")
    return new Promise((resolve) => { live.finish = () => resolve({ working: true, completion: "" }) })
  })
  return live
}

beforeEach(() => {
  vi.clearAllMocks()
  mode.local = false
  localStorage.clear()
  Element.prototype.scrollIntoView = vi.fn()
  getChatHistory.mockResolvedValue({ messages: HISTORY, truncated: false })
})
afterEach(() => cleanup())

describe("ChatPanel resume (Cloud)", () => {
  it("cuts the history at the work's prompt, replays it once and follows it live until idle", async () => {
    storeState(SESSION, "working")
    const live = workingResume()
    renderWithIntl(<ChatPanel deckId="d1" />)
    await waitFor(() => expect(resumeAgentCore).toHaveBeenCalledWith(SESSION, "at", 0, expect.anything()))
    expect(screen.getAllByText("make it")).toHaveLength(1)
    expect(screen.queryByText("stale partial")).toBeNull()
    expect(screen.getByText("earlier reply")).toBeTruthy()
    expect(screen.getByText("Hel")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Stop generation" })).toBeTruthy()

    act(() => live.handlers!.onStreamUpdate("Hello"))
    expect(screen.getByText("Hello")).toBeTruthy()

    await act(async () => { live.finish!() })
    expect(screen.queryByRole("button", { name: "Stop generation" })).toBeNull()
  })

  it("keeps the history when the session is no longer working", async () => {
    storeState(SESSION, "working")
    resumeAgentCore.mockImplementationOnce(async (_s: string, _t: string, _f: number, h: ResumeHandlers) => {
      h.onResumeAck({ working: false })
      return { working: false, completion: "" }
    })
    renderWithIntl(<ChatPanel deckId="d1" />)
    await waitFor(() => expect(resumeAgentCore).toHaveBeenCalled())
    expect(screen.getByText("stale partial")).toBeTruthy()
    expect(screen.getAllByText("make it")).toHaveLength(1)
    expect(screen.queryByRole("button", { name: "Stop generation" })).toBeNull()
  })

  it("opens no connection for a session last seen idle", async () => {
    storeState(SESSION, "idle")
    renderWithIntl(<ChatPanel deckId="d1" />)
    await waitFor(() => expect(screen.getByText("stale partial")).toBeTruthy())
    expect(resumeAgentCore).not.toHaveBeenCalled()
  })

  it("stops the resumed session with a cancel", async () => {
    storeState(SESSION, "working")
    const live = workingResume()
    cancelAgentCore.mockResolvedValueOnce("stopped")
    renderWithIntl(<ChatPanel deckId="d1" />)
    const stop = await screen.findByRole("button", { name: "Stop generation" })
    fireEvent.click(stop)
    expect(cancelAgentCore).toHaveBeenCalledWith(SESSION, "at")
    await act(async () => { live.finish!() })
  })

  it("rebuilds a background compose after a reload and follows it to its result", async () => {
    const BACKGROUND = "Composers are working in the background. You can keep chatting."
    const input = { slide_groups: [{ slugs: ["intro"], instruction: "a" }, { slugs: ["body"], instruction: "b" }] }
    const stream = (data: Record<string, unknown>) => ({ toolUseId: "c1", name: "compose_slides", stream: true, data })
    storeState(SESSION, "working")
    const live: { handlers?: ResumeHandlers; finish?: () => void } = {}
    resumeAgentCore.mockImplementationOnce((_sid: string, _tok: string, _from: number, h: ResumeHandlers) => {
      live.handlers = h
      h.onResumeAck({ working: true })
      h.onSession.onEvent({ work: { state: "busy" } }, { own: false })
      h.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: false })
      h.onStreamUpdate("Composing.")
      h.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", input: {}, started: true })
      h.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", input })
      h.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", taskStarted: true, task: { id: "t", state: "running" } })
      h.onSession.onEvent({ turnEnd: { id: "p1", how: "finished" } }, { own: false })
      h.onToolUse("compose_slides", stream({ status: "starting", group: 1, total_groups: 2, slugs: "intro" }))
      h.onToolUse("compose_slides", stream({ status: "starting", group: 2, total_groups: 2, slugs: "body" }))
      return new Promise((resolve) => { live.finish = () => resolve({ working: true, completion: "" }) })
    })
    renderWithIntl(<ChatPanel deckId="d1" />)
    await waitFor(() => expect(screen.getByText("2 slides in production")).toBeTruthy())
    expect(screen.queryByText("stale partial")).toBeNull()
    expect(screen.getByText(BACKGROUND)).toBeTruthy()

    const h = live.handlers!
    act(() => h.onToolUse("compose_slides", stream({ status: "done", group: 1, slugs: "intro" })))
    expect(screen.getByText("1 / 2 created")).toBeTruthy()

    act(() => {
      h.onToolUse("compose_slides", stream({ status: "done", group: 2, slugs: "body" }))
      h.onToolUse("compose_slides", {
        toolUseId: "c1", name: "compose_slides", completed: true, status: "success",
        result: { status: "success" }, task: { id: "t", state: "completed" },
      })
      h.onSession.onEvent({ turn: { id: "w1", why: "wake", text: "" } }, { own: false })
      h.onStreamUpdate("Composing.\n\nAll slides are ready.")
    })
    expect(screen.getByText("Composed 2 slides")).toBeTruthy()
    expect(screen.queryByText(BACKGROUND)).toBeNull()
    expect(screen.getByText("All slides are ready.")).toBeTruthy()

    act(() => h.onSession.onEvent({ work: { state: "idle", how: "finished" } }, { own: false }))
    await act(async () => { live.finish!() })
    expect(screen.getByText("Composed 2 slides")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Stop generation" })).toBeNull()
  })
})

describe("ChatPanel resume (Local)", () => {
  it("does not resume", async () => {
    mode.local = true
    const localSession = "d1".padEnd(36, "0")
    storeState(localSession, "working")
    getChatHistory.mockResolvedValue({ messages: [], truncated: false })
    renderWithIntl(<ChatPanel deckId="d1" />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(resumeAgentCore).not.toHaveBeenCalled()
  })
})
