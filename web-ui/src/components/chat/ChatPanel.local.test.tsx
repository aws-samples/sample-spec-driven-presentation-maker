// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel (Local mode): a reply that ran in a new kiro session because the deck had none to
 * load shows the translated "earlier conversation not carried over" notice, also when it comes
 * back from `.chat.json`. A deck follows its chat's work period after `.chat.json` loads
 * (resumeLocalAgent, no EventSource): the replay rebuilds the period from its prompt, the Stop
 * button and the background line show while it runs, and the chat is saved on a task's start
 * and end and on a turn's end. A task still running in the history while nothing runs shows
 * stopped.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import en from "../../../messages/en.json"

const { getChatHistory, resumeLocalAgent, saveLocalChat } = vi.hoisted(() => ({
  getChatHistory: vi.fn(), resumeLocalAgent: vi.fn(), saveLocalChat: vi.fn(async () => undefined),
}))

vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: undefined }
  return { useAuth: () => auth }
})
vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn(), info: vi.fn(), error: vi.fn() }) }))
vi.mock("@/services/agentCoreService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/agentCoreService")>()),
  invokeAgentCore: vi.fn(),
  resumeLocalAgent,
}))
vi.mock("@/services/localService", () => ({
  saveLocalChat,
  stopLocalAgent: vi.fn(async () => undefined),
  getLocalSessionModels: vi.fn(async () => null),
  setLocalSessionModel: vi.fn(async () => null),
}))
vi.mock("@/services/deckService", () => ({
  getChatHistory,
  patchDeck: vi.fn(),
  createReview: vi.fn(),
  batchGetSlidePreviewUrls: vi.fn(async () => new Map()),
  fetchStyles: vi.fn(async () => []),
  fetchTemplates: vi.fn(async () => []),
}))
vi.mock("@/services/kiroSessionsService", () => ({ forkKiroSession: vi.fn(), listKiroSessions: vi.fn(async () => ({ recent: [] })) }))

import { ChatPanel } from "./ChatPanel"

beforeEach(() => {
  vi.clearAllMocks()
  Element.prototype.scrollIntoView = vi.fn()
  resumeLocalAgent.mockImplementation(async (_sid: string, h: ResumeHandlers) => {
    h.onResumeAck({ working: false })
    return { working: false, completion: "" }
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type ResumeHandlers = {
  onResumeAck: (ack: { working: boolean }) => void
  onStreamUpdate: (text: string) => void
  onToolUse: (name: string, data: Record<string, unknown>) => void
  onSession: { onEvent: (ev: Record<string, unknown>, info: { own: boolean }) => void }
}

const HISTORY = [
  { role: "user", content: "earlier", toolUses: [] },
  { role: "assistant", content: "earlier reply", toolUses: [] },
  { role: "user", content: "make it", toolUses: [] },
  { role: "assistant", content: "stale partial", toolUses: [] },
]
const BACKGROUND = en.chat.backgroundWorking

/** resumeLocalAgent that replays the start of a working period; returns live controls. */
function workingResume() {
  const live: { sessionId?: string; handlers?: ResumeHandlers; finish?: () => void } = {}
  resumeLocalAgent.mockImplementationOnce((sessionId: string, h: ResumeHandlers) => {
    Object.assign(live, { sessionId, handlers: h })
    h.onResumeAck({ working: true })
    h.onSession.onEvent({ work: { state: "busy" } }, { own: false })
    h.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: false })
    h.onStreamUpdate("Hel")
    return new Promise((resolve) => { live.finish = () => resolve({ working: true, completion: "" }) })
  })
  return live
}

describe("ChatPanel resume (Local)", () => {
  it("follows the deck's chat after .chat.json loads and rebuilds the period from its prompt", async () => {
    const eventSource = vi.fn()
    vi.stubGlobal("EventSource", eventSource)
    getChatHistory.mockResolvedValue({ messages: HISTORY, truncated: false })
    const live = workingResume()
    renderWithIntl(<ChatPanel deckId="d1" chatSessionId="S1" />)
    expect(await screen.findByText("Hel")).toBeTruthy()
    expect(live.sessionId).toBe("S1")
    expect(screen.getAllByText("make it")).toHaveLength(1)
    expect(screen.queryByText("stale partial")).toBeNull()
    expect(screen.getByText("earlier reply")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Stop generation" })).toBeTruthy()
    expect(eventSource).not.toHaveBeenCalled()

    await act(async () => { live.finish!() })
    expect(screen.queryByRole("button", { name: "Stop generation" })).toBeNull()
  })

  it("shows a task the history has running as stopped when nothing runs", async () => {
    const tool = {
      toolUseId: "c1", name: "compose_slides", task: { id: "k1", state: "running" },
      input: { slide_groups: [{ slugs: ["intro"], instruction: "a" }, { slugs: ["body"], instruction: "b" }] },
      streamMessages: [{ status: "starting", group: 1, total_groups: 2, slugs: "intro" }],
    }
    getChatHistory.mockResolvedValue({
      messages: [...HISTORY.slice(0, 3), { role: "assistant", content: "Composing.", toolUses: [tool], blocks: [{ type: "text", text: "Composing." }, { type: "tool", tool }] }],
      truncated: false,
    })
    renderWithIntl(<ChatPanel deckId="d1" chatSessionId="S1" />)
    await waitFor(() => expect(resumeLocalAgent).toHaveBeenCalled())
    await waitFor(() => expect(screen.getAllByText("Stopped").length).toBeGreaterThan(0))
    expect(screen.queryByText("2 slides in production")).toBeNull()
  })

  it("shows the background line and saves the chat on a task's start and end and a turn's end", async () => {
    getChatHistory.mockResolvedValue({ messages: HISTORY, truncated: false })
    const live = workingResume()
    renderWithIntl(<ChatPanel deckId="d1" chatSessionId="S1" />)
    await screen.findByText("Hel")
    const h = live.handlers!
    const saved = async (step: () => void) => {
      saveLocalChat.mockClear()
      act(step)
      await waitFor(() => expect(saveLocalChat).toHaveBeenCalled())
    }
    act(() => {
      h.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", input: {}, started: true })
      h.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", input: { slide_groups: [{ slugs: ["intro"], instruction: "a" }] } })
    })
    await saved(() => h.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", taskStarted: true, task: { id: "k1", state: "running" } }))
    await saved(() => h.onSession.onEvent({ turnEnd: { id: "p1", how: "finished" } }, { own: false }))
    expect(screen.getByText(BACKGROUND)).toBeTruthy()
    await saved(() => h.onToolUse("compose_slides", {
      toolUseId: "c1", name: "compose_slides", completed: true, status: "success", result: { status: "success" }, task: { id: "k1", state: "completed" },
    }))
    expect(screen.queryByText(BACKGROUND)).toBeNull()
    await act(async () => { live.finish!() })
  })
})

describe("ChatPanel session notice (Local)", () => {
  it("shows the notice above the reply it belongs to", async () => {
    getChatHistory.mockResolvedValue({
      messages: [
        { role: "user", content: "hi", toolUses: [] },
        { role: "assistant", content: "OK", toolUses: [], localNotice: "context_not_carried_over" },
        { role: "user", content: "next", toolUses: [] },
        { role: "assistant", content: "Done", toolUses: [] },
      ],
      truncated: false,
    })
    renderWithIntl(<ChatPanel deckId="mcp-made-deck" />)
    expect(await screen.findByText("OK")).toBeTruthy()
    expect(screen.getAllByText(en.chat.localContextNotCarriedOver)).toHaveLength(1)
  })
})
