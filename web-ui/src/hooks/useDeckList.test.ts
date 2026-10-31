// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: false }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock("@/services/deckService", () => ({
  listDecks: vi.fn(),
  listPublicDecks: vi.fn(),
  listSharedDecks: vi.fn(),
  listFavorites: vi.fn(),
  searchSlides: vi.fn(),
  updateVisibility: vi.fn(),
  deleteDeck: vi.fn(),
  toggleFavorite: vi.fn(),
}))

import * as deckService from "@/services/deckService"
import { useDeckList } from "./useDeckList"

const api = vi.mocked(deckService)
const MIN = 60 * 1000

/** Let pending promises (mocked API calls) settle under fake timers. */
async function flush() {
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
}

describe("useDeckList — HTML preview URL re-signing", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    api.listDecks.mockResolvedValue({ decks: [], favoriteIds: [] } as never)
    api.listPublicDecks.mockResolvedValue([] as never)
    api.listSharedDecks.mockResolvedValue([] as never)
    api.listFavorites.mockResolvedValue([] as never)
    api.searchSlides.mockResolvedValue([
      { deckId: "d1", slug: "cover", previewUrl: "https://bucket.s3.amazonaws.com/html/d1/preview/cover_1.html?X-Amz-Signature=a" },
    ] as never)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  async function searchOnce(activeDeckId: string | null = null) {
    const hook = renderHook(({ active }) => useDeckList("token", true, active), {
      initialProps: { active: activeDeckId },
    })
    await flush()
    act(() => hook.result.current.setSearchQuery("cover"))
    await act(async () => { vi.advanceTimersByTime(300) })  // search debounce
    await flush()
    expect(api.searchSlides).toHaveBeenCalledTimes(1)
    return hook
  }

  it("re-runs the search silently once its signed URLs are 10 minutes old", async () => {
    await searchOnce()
    await act(async () => { vi.advanceTimersByTime(9 * MIN) })
    expect(api.searchSlides).toHaveBeenCalledTimes(1)
    await act(async () => { vi.advanceTimersByTime(1 * MIN) })
    await flush()
    expect(api.searchSlides).toHaveBeenCalledTimes(2)
  })

  it("re-signs search results at once when the list view returns after a long deck visit", async () => {
    const hook = await searchOnce()
    hook.rerender({ active: "d1" })  // open a deck: the list view unmounts its timers
    await act(async () => { vi.advanceTimersByTime(20 * MIN) })
    expect(api.searchSlides).toHaveBeenCalledTimes(1)
    hook.rerender({ active: null })  // back to the list
    await flush()
    expect(api.searchSlides).toHaveBeenCalledTimes(2)
  })

  it("does not re-run a fresh search when the list view returns quickly", async () => {
    const hook = await searchOnce()
    hook.rerender({ active: "d1" })
    await act(async () => { vi.advanceTimersByTime(2 * MIN) })
    hook.rerender({ active: null })
    await flush()
    expect(api.searchSlides).toHaveBeenCalledTimes(1)
  })
})
