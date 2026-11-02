// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local mode: the deck list opens PPTX files and folders in the OS through localService. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { toast } from "sonner"
import { intlWrapper } from "@/test/renderWithIntl"
import en from "../../messages/en.json"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: true }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock("@/services/deckService", () => ({
  listDecks: vi.fn(),
  listPublicDecks: vi.fn(),
  listFavorites: vi.fn(),
  searchSlides: vi.fn(),
  updateVisibility: vi.fn(),
  deleteDeck: vi.fn(),
  toggleFavorite: vi.fn(),
}))
vi.mock("@/services/localService", () => ({ openInOs: vi.fn() }))

import * as deckService from "@/services/deckService"
import { openInOs } from "@/services/localService"
import { useDeckList } from "./useDeckList"

const api = vi.mocked(deckService)
const DECK = { deckId: "d1", name: "Deck", pptxUrl: "/api/decks/d1/pptx" }

async function renderList() {
  const hook = renderHook(() => useDeckList("local", true, null), { wrapper: intlWrapper() })
  await waitFor(() => expect(hook.result.current.decks).toHaveLength(1))
  return hook
}

describe("useDeckList (local) — open in the OS", () => {
  beforeEach(() => {
    api.listDecks.mockResolvedValue({ decks: [DECK], favoriteIds: [] } as never)
    api.listPublicDecks.mockResolvedValue([] as never)
    api.listFavorites.mockResolvedValue([] as never)
    vi.mocked(openInOs).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it("opens the PPTX and the deck folder", async () => {
    const { result } = await renderList()
    act(() => result.current.handleDownload("d1"))
    act(() => result.current.handleOpenFolder("d1"))
    expect(openInOs).toHaveBeenNthCalledWith(1, "d1", "output.pptx")
    expect(openInOs).toHaveBeenNthCalledWith(2, "d1")
  })

  it("reports failures with the translated carousel messages", async () => {
    vi.mocked(openInOs).mockRejectedValue(new Error("HTTP 500"))
    vi.spyOn(console, "error").mockImplementation(() => {})
    const { result } = await renderList()
    act(() => result.current.handleDownload("d1"))
    act(() => result.current.handleOpenFolder("d1"))
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2))
    expect(toast.error).toHaveBeenCalledWith(en.carousel.errorOpenPptx, undefined)
    expect(toast.error).toHaveBeenCalledWith(en.carousel.errorOpenFolder, undefined)
  })
})
