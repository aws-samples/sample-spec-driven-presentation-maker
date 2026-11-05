// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel (Local mode): a reply that ran in a new kiro session because the deck had none to
 * load shows the translated "earlier conversation not carried over" notice, also when it comes
 * back from `.chat.json`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import en from "../../../messages/en.json"

const { getChatHistory } = vi.hoisted(() => ({ getChatHistory: vi.fn() }))

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
}))
vi.mock("@/services/localService", () => ({
  saveLocalChat: vi.fn(async () => undefined),
  localStreamUrl: vi.fn(() => null),
  hasLocalStream: vi.fn(async () => false),
  stopLocalAgent: vi.fn(),
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

describe("ChatPanel session notice (Local)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
  })
  afterEach(() => cleanup())

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
