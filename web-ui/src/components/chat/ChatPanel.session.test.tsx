// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel session ids (Cloud mode): a new chat and a deck without a linked chat get ids
 * with the owner prefix of the signed-in user; a linked chat of an earlier format is kept
 * while it has history and replaced by the user's own deck id when it has none.
 */

import { createRef } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { deckSessionId, ownerPrefix } from "@/lib/sessionId"

const { invokeAgentCore, getChatHistory } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(),
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
  invokeAgentCore,
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
