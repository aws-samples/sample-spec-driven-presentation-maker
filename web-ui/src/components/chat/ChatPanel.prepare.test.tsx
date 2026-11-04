// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel prepare (Cloud, first-response-latency R4): the new deck screen sends one
 * `prepare` when it is first shown (not when a page loads with it hidden) — not again on re-renders, mode changes or later — and none for
 * an existing deck or in Local mode. A send before `ready` goes over the prepare socket;
 * after `ready` that socket closes.
 */

import { createRef } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { FakeWebSocket } from "@/test/fakeWebSocket"

const mode = vi.hoisted(() => ({ local: false }))
const { getChatHistory } = vi.hoisted(() => ({ getChatHistory: vi.fn() }))

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
  loadRuntimeConfig: vi.fn(async () => ({ agentRuntimeArn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/a", awsRegion: "us-east-1" })),
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
}))
vi.mock("@/services/kiroSessionsService", () => ({ forkKiroSession: vi.fn(), listKiroSessions: vi.fn(async () => ({ recent: [] })) }))

import { ChatPanel, type ChatPanelHandle } from "./ChatPanel"
import { ChatPanelShell } from "./ChatPanelShell"

const prepares = () => FakeWebSocket.instances.flatMap((ws) => ws.ofType("prepare"))

/** Render the new deck screen and open the prepare socket. */
async function renderNewDeck() {
  const ref = createRef<ChatPanelHandle>()
  const view = renderWithIntl(<ChatPanel ref={ref} deckId="new" />)
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
  const ws = FakeWebSocket.last()
  act(() => ws.open())
  return { ref, view, ws }
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.stubGlobal("WebSocket", FakeWebSocket)
  FakeWebSocket.reset()
  mode.local = false
  localStorage.clear()
  Element.prototype.scrollIntoView = vi.fn()
  getChatHistory.mockResolvedValue({ messages: [], truncated: false })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("ChatPanel prepare (Cloud)", () => {
  it("sends one prepare when the new deck screen opens, and none after re-renders, a mode change or 20 minutes", async () => {
    const { view, ws } = await renderNewDeck()
    expect(prepares()).toEqual([{ type: "prepare", mode: "spec" }])
    act(() => ws.receive({ ctl: "prepareAck" }))
    await act(async () => { ws.receive({ ctl: "ready", mcp_status: [] }) })
    expect(ws.closedWith).toBe(1000)

    view.rerender(<ChatPanel deckId="new" onLoadingChange={() => {}} />)
    fireEvent.click(screen.getByRole("button", { name: /Vibe/ }))
    await act(async () => { vi.advanceTimersByTime(20 * 60 * 1000) })
    expect(prepares()).toHaveLength(1)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("carries a send before ready over the prepare socket and keeps it open for the work", async () => {
    const { ref, ws } = await renderNewDeck()
    act(() => ws.receive({ ctl: "prepareAck" }))
    await act(async () => { void ref.current!.sendMessage("make a deck") })
    expect(FakeWebSocket.instances).toHaveLength(1)
    const prompt = ws.ofType("prompt")[0]
    expect(prompt).toMatchObject({ prompt: "make a deck" })
    await act(async () => {
      ws.receive({ ctl: "accepted", id: prompt.id, as: "turn", head: 2 })
      ws.receive({ ctl: "ready", mcp_status: [] })
    })
    expect(ws.closedWith).toBeUndefined()
    await act(async () => { ws.receive({ batch: [{ seq: 1, ev: { work: { state: "busy" } } }, { seq: 2, ev: { work: { state: "idle", how: "finished" } } }] }) })
    expect(ws.closedWith).toBe(1000)
  })

  it("waits until the new deck screen is shown, then prepares once", async () => {
    const view = renderWithIntl(<ChatPanel deckId="new" visible={false} />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(FakeWebSocket.instances).toHaveLength(0)

    view.rerender(<ChatPanel deckId="new" visible />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.last()
    act(() => ws.open())
    expect(prepares()).toHaveLength(1)

    view.rerender(<ChatPanel deckId="new" visible={false} />)
    view.rerender(<ChatPanel deckId="new" visible />)
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("does not prepare when a page loads with the chat closed or on a deck's own tab", async () => {
    const shell = (open: boolean, chatTab: "new" | "deck", deckId: string | null) => (
      <ChatPanelShell open={open} onClose={() => {}} chatTab={chatTab} onChatTabChange={() => {}} deckId={deckId} deckName="d" />
    )
    const view = renderWithIntl(shell(false, "new", null))
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(FakeWebSocket.instances).toHaveLength(0)

    view.rerender(shell(true, "deck", "d1"))
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(FakeWebSocket.instances).toHaveLength(0)

    // New Deck: the chat opens on the New tab.
    view.rerender(shell(true, "new", "d1"))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    act(() => FakeWebSocket.last().open())
    expect(prepares()).toEqual([{ type: "prepare", mode: "spec" }])
  })

  it("does not prepare an existing deck", async () => {
    renderWithIntl(<ChatPanel deckId="d1" />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(FakeWebSocket.instances).toHaveLength(0)
  })
})

describe("ChatPanel prepare (Local)", () => {
  it("does not prepare", async () => {
    mode.local = true
    renderWithIntl(<ChatPanel deckId="new" />)
    await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(FakeWebSocket.instances).toHaveLength(0)
  })
})
