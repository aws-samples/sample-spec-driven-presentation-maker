// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel session ids (Cloud mode): a new chat and a deck without a linked chat get ids
 * with the owner prefix of the signed-in user; a linked chat of an earlier format is kept
 * while it has history and replaced by the user's own deck id when it has none.
 */

import { createRef } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { deckSessionId, ownerPrefix } from "@/lib/sessionId"

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

    act(() => { h!.onSession.onEvent({ composerNote: { toolUseId: "c1", group: 1, slugs: "intro", text: "Done with intro." } }, { own: false }) })
    expect(screen.getByRole("note", { name: "Message with composer 1" }).textContent).toContain("Done with intro.")

    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "steer" })
    await act(async () => { await ref.current!.sendMessage("use blue") })
    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => { h!.onSession.onEvent({ steer: { id: steerId, text: "use blue", state: "accepted" } }, { own: true }) })
    expect(screen.getByText("Sent while the agent works")).toBeTruthy()
    act(() => {
      h!.onSession.onEvent({ steer: { id: steerId, state: "delivered", how: "turn" } }, { own: true })
      h!.onSession.onEvent({ turn: { id: steerId, why: "steer", text: "use blue" } }, { own: true })
    })
    expect(screen.getByText("Read by the agent")).toBeTruthy()
    expect(screen.queryByText(BACKGROUND)).toBeNull()

    await act(async () => { finish!() })
    expect(screen.queryByText(BACKGROUND)).toBeNull()
  })
})
