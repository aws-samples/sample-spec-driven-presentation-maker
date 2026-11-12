// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel session ids (Cloud mode): a new chat and a deck without a linked chat get ids
 * with the owner prefix of the signed-in user; a linked chat of an earlier format is kept
 * while it has history and replaced by the user's own deck id when it has none.
 *
 * ChatPanel steers (Cloud mode): a message sent while the agent works clears the input and
 * waits as a card above it until the agent reads it, then becomes a bubble; a steer that
 * could not be sent goes back into the input; a not-delivered one can go back or be dismissed.
 */

import { createRef } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { deckSessionId, ownerPrefix } from "@/lib/sessionId"
import composerNote from "@/test/fixtures/composerNote.json"
import en from "../../../messages/en.json"

const { invokeAgentCore, steerAgentCore, getChatHistory } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(),
  steerAgentCore: vi.fn(),
  getChatHistory: vi.fn(),
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
  steerAgentCore,
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

import { ChatPanel, type ChatPanelHandle } from "./ChatPanel"

const LEGACY = "0f8c6a4e-2b1d-4c3e-9a7f-5d6e7f8a9b0c"
const HISTORY = [
  { role: "user", content: [{ text: "hello" }] },
  { role: "assistant", content: [{ text: "hi" }] },
]

/** Render, wait for the history load(s), send one message and return the session id it used. */
async function sentSessionId(props: { deckId: string; chatSessionId?: string }, historyCalls = 1): Promise<string> {
  const ref = createRef<ChatPanelHandle>()
  renderWithIntl(<ChatPanel ref={ref} {...props} />)
  await waitFor(() => expect(getChatHistory).toHaveBeenCalledTimes(historyCalls))
  await act(async () => { await ref.current!.sendMessage("go") })
  await waitFor(() => expect(invokeAgentCore).toHaveBeenCalled())
  return invokeAgentCore.mock.calls[0][1] as string
}

describe("ChatPanel session ids (Cloud)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    getChatHistory.mockResolvedValue({ messages: [], truncated: false })
    invokeAgentCore.mockResolvedValue("")
  })
  afterEach(() => cleanup())

  it("gives a new chat an id with the user's prefix", async () => {
    const id = await sentSessionId({ deckId: "new" })
    expect(id.startsWith(`${ownerPrefix("u1")}-`)).toBe(true)
    expect(id).toHaveLength(53)
  })

  it("gives a deck without a linked chat the user's deck id", async () => {
    expect(await sentSessionId({ deckId: "d1" })).toBe(deckSessionId("u1", "d1"))
  })

  it("keeps a linked chat of an earlier format that has history", async () => {
    getChatHistory.mockResolvedValue({ messages: HISTORY, truncated: false })
    expect(await sentSessionId({ deckId: "d1", chatSessionId: LEGACY })).toBe(LEGACY)
  })

  it("replaces a linked chat of an earlier format that has no history", async () => {
    expect(await sentSessionId({ deckId: "d1", chatSessionId: LEGACY }, 2)).toBe(deckSessionId("u1", "d1"))
    expect(getChatHistory.mock.calls.map((c) => c[0])).toEqual([LEGACY, deckSessionId("u1", "d1")])
  })
})

type Handlers = {
  onStreamUpdate: (text: string) => void
  onToolUse: (name: string, data: Record<string, unknown>) => void
  onSession: { onEvent: (ev: Record<string, unknown>, info: { own: boolean }) => void }
}

describe("ChatPanel background compose (Cloud)", () => {
  const BACKGROUND = "Composers are working in the background. You can keep chatting."

  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    getChatHistory.mockResolvedValue({ messages: [], truncated: false })
  })
  afterEach(() => cleanup())

  it("shows the background line between turns, composer notes and steer delivery", async () => {
    let h: Handlers | undefined
    let finish: (() => void) | undefined
    invokeAgentCore.mockImplementationOnce((...args: unknown[]) => new Promise<string>((resolve) => {
      h = { onStreamUpdate: args[2], onToolUse: args[5], onSession: args[11] } as Handlers
      finish = () => resolve("")
    }))
    const ref = createRef<ChatPanelHandle>()
    renderWithIntl(<ChatPanel ref={ref} deckId="d1" />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await waitFor(() => expect(ref.current).toBeTruthy())
    act(() => { void ref.current!.sendMessage("make it") })
    await waitFor(() => expect(h).toBeDefined())

    act(() => {
      h!.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: true })
      h!.onStreamUpdate("Composing.")
      h!.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", input: {}, started: true })
    })
    expect(screen.queryByText(BACKGROUND)).toBeNull()
    act(() => {
      h!.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", taskStarted: true, task: { id: "t", state: "running" } })
      h!.onSession.onEvent({ turnEnd: { id: "p1", how: "finished" } }, { own: true })
    })
    expect(screen.getByText(BACKGROUND)).toBeTruthy()

    // The agent's real composerNote payload (tests/test_agent_compose_messaging.py checks the same file).
    act(() => { h!.onSession.onEvent(composerNote.event, { own: false }) })
    const note = screen.getByRole("note", { name: "Message with composer 1" })
    expect(note.textContent).toContain("· intro, agenda")
    expect(note.textContent).toContain(composerNote.event.composerNote.text)

    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "steer" })
    await act(async () => { await ref.current!.sendMessage("use blue") })
    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => { h!.onSession.onEvent({ steer: { id: steerId, text: "use blue", state: "accepted" } }, { own: true }) })
    expect(screen.getByText(en.chat.steerWaiting)).toBeTruthy()
    act(() => {
      h!.onSession.onEvent({ steer: { id: steerId, state: "delivered", how: "turn" } }, { own: true })
      h!.onSession.onEvent({ turn: { id: steerId, why: "steer", text: "use blue" } }, { own: true })
    })
    expect(screen.queryByText(en.chat.steerWaiting)).toBeNull()
    expect(within(screen.getByRole("log")).getByText("use blue")).toBeTruthy()
    expect(screen.queryByText(BACKGROUND)).toBeNull()

    await act(async () => { finish!() })
    expect(screen.queryByText(BACKGROUND)).toBeNull()
  })

  it("shows the background line only while a task runs", async () => {
    let h: Handlers | undefined
    let finish: (() => void) | undefined
    invokeAgentCore.mockImplementationOnce((...args: unknown[]) => new Promise<string>((resolve) => {
      h = { onStreamUpdate: args[2], onToolUse: args[5], onSession: args[11] } as Handlers
      finish = () => resolve("")
    }))
    const ref = createRef<ChatPanelHandle>()
    renderWithIntl(<ChatPanel ref={ref} deckId="d1" />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await waitFor(() => expect(ref.current).toBeTruthy())
    act(() => { void ref.current!.sendMessage("make it") })
    await waitFor(() => expect(h).toBeDefined())

    act(() => {
      h!.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: true })
      h!.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", input: {}, started: true })
      h!.onToolUse("compose_slides", { toolUseId: "c1", name: "compose_slides", taskStarted: true, task: { id: "t", state: "running" } })
      h!.onSession.onEvent({ turnEnd: { id: "p1", how: "finished" } }, { own: true })
    })
    expect(screen.getByText(BACKGROUND)).toBeTruthy()
    act(() => {
      h!.onToolUse("compose_slides", {
        toolUseId: "c1", name: "compose_slides", status: "success", completed: true, task: { id: "t", state: "completed" },
      })
    })
    expect(screen.queryByText(BACKGROUND)).toBeNull()  // still working (a wake turn comes), no task runs

    await act(async () => { finish!() })
  })
})

describe("ChatPanel steers (Cloud)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    getChatHistory.mockResolvedValue({ messages: [], truncated: false })
  })
  afterEach(() => cleanup())

  const textbox = () => screen.getByRole("textbox", { name: en.chatInput.inputLabel }) as HTMLTextAreaElement
  const queue = () => screen.queryByRole("region", { name: en.chat.steerQueue })

  /** Render a chat whose agent works on a first prompt; returns its stream handlers. */
  async function working() {
    let h: Handlers | undefined
    let finish: (() => void) | undefined
    invokeAgentCore.mockImplementationOnce((...args: unknown[]) => new Promise<string>((resolve) => {
      h = { onStreamUpdate: args[2], onToolUse: args[5], onSession: args[11] } as Handlers
      finish = () => resolve("")
    }))
    const ref = createRef<ChatPanelHandle>()
    renderWithIntl(<ChatPanel ref={ref} deckId="d1" />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await waitFor(() => expect(ref.current).toBeTruthy())
    act(() => { void ref.current!.sendMessage("make it") })
    await waitFor(() => expect(h).toBeDefined())
    act(() => { h!.onStreamUpdate("Working.") })
    await waitFor(() => expect(textbox().disabled).toBe(false))
    return { h: h!, finish: () => finish!() }
  }

  async function send(text: string) {
    fireEvent.change(textbox(), { target: { value: text } })
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: en.chatInput.sendMessage })) })
  }

  it("clears the input at once and shows the steer as a card until the agent reads it", async () => {
    const { h, finish } = await working()
    let answer: ((v: unknown) => void) | undefined
    steerAgentCore.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve }))
    await send("use blue")
    expect(textbox().value).toBe("")
    const log = screen.getByRole("log")
    expect(within(queue()!).getByText("use blue")).toBeTruthy()
    expect(within(queue()!).getByText(en.chat.steerSending)).toBeTruthy()
    expect(within(log).queryByText("use blue")).toBeNull()

    await act(async () => { answer!({ id: "x", as: "steer" }) })
    expect(within(queue()!).getByText(en.chat.steerWaiting)).toBeTruthy()

    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => { h.onSession.onEvent({ steer: { id: steerId, text: "use blue", state: "accepted" } }, { own: true }) })
    expect(within(log).queryByText("use blue")).toBeNull()
    act(() => {
      h.onSession.onEvent({ steer: { id: steerId, state: "delivered", how: "fold" } }, { own: true })
      h.onStreamUpdate("Working. Blue it is.")
    })
    expect(queue()).toBeNull()
    const bubble = within(log).getByText("use blue")
    expect(bubble.closest(".steer-arrived")).not.toBeNull()
    expect(within(log).getByText("Blue it is.")).toBeTruthy()
    await act(async () => { finish() })
  })

  it("puts the text back into the input when the steer could not be sent", async () => {
    const { finish } = await working()
    steerAgentCore.mockRejectedValueOnce(new Error("timeout"))
    await send("use blue")
    await waitFor(() => expect(textbox().value).toBe("use blue"))
    expect(queue()).toBeNull()
    await act(async () => { finish() })
  })

  it("offers back to input and dismiss for steers that were not delivered", async () => {
    const { h, finish } = await working()
    steerAgentCore.mockResolvedValue({ id: "x", as: "steer" })
    await send("first")
    await send("second")
    const [a, b] = steerAgentCore.mock.calls.map((call) => call[3] as string)
    act(() => {
      h.onSession.onEvent({ steer: { id: a, text: "first", state: "accepted" } }, { own: true })
      h.onSession.onEvent({ steer: { id: b, text: "second", state: "accepted" } }, { own: true })
      h.onSession.onEvent({ steer: { id: a, state: "discarded", how: "cancelled" } }, { own: true })
      h.onSession.onEvent({ steer: { id: b, state: "discarded", how: "cancelled" } }, { own: true })
    })
    const cards = within(queue()!).getAllByRole("listitem")
    expect(cards.map((c) => c.textContent)).toEqual([
      expect.stringContaining("first"), expect.stringContaining("second"),
    ])
    expect(within(queue()!).getAllByText(en.chat.steerNotDelivered)).toHaveLength(2)

    fireEvent.change(textbox(), { target: { value: "draft" } })
    fireEvent.click(within(cards[0]).getByRole("button", { name: en.chat.steerBackToInput }))
    await waitFor(() => expect(textbox().value).toBe("draft\n\nfirst"))
    expect(within(queue()!).getAllByRole("listitem")).toHaveLength(1)

    fireEvent.click(within(queue()!).getByRole("button", { name: en.chat.steerDismiss }))
    expect(queue()).toBeNull()
    await act(async () => { finish() })
  })
})
