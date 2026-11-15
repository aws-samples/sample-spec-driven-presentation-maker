// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useStyleWorkspace preview: opening a style reads the preloaded list; a refresh after the
 * agent saved fetches the saved HTML, because the list still holds the style from before the
 * save (the preview used to show every save one save late). The old preview stays on screen
 * while it fetches, and a failed fetch keeps it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"

const { fetchStylePreviewHtml } = vi.hoisted(() => ({ fetchStylePreviewHtml: vi.fn(async (..._args: unknown[]) => "") }))
vi.mock("@/services/deckService", () => ({ fetchStylePreviewHtml }))

import { useStyleWorkspace } from "./useStyleWorkspace"
import type { StyleEntry } from "@/services/deckService"

const entry = (html: string) => ({ name: "calm", html }) as unknown as StyleEntry

async function openCalm() {
  window.location.hash = "#calm"
  // Let jsdom's hashchange for this assignment fire before the hook listens.
  await new Promise((resolve) => setTimeout(resolve, 0))
  return renderHook(() => useStyleWorkspace("tok"))
}

describe("useStyleWorkspace preview", () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(async () => {
    // Unmount first: vitest runs without globals, so Testing Library's auto-cleanup is off.
    // A hook still mounted here would re-render on the hashchange below, after jsdom is gone.
    cleanup()
    window.location.hash = ""
    await new Promise((resolve) => setTimeout(resolve, 0))
  })

  it("opens a style from the preloaded list without a fetch", async () => {
    const hook = await openCalm()
    act(() => { hook.result.current.setStyles([entry("<p>v1</p>")]) })
    act(() => { hook.result.current.refreshPreview() })
    // The refresh fetches; a plain open with the list loaded does not.
    fetchStylePreviewHtml.mockClear()
    hook.rerender()
    expect(fetchStylePreviewHtml).not.toHaveBeenCalled()
  })

  it("shows the saved HTML right after a save, not the list's older copy", async () => {
    const hook = await openCalm()
    await waitFor(() => expect(fetchStylePreviewHtml).toHaveBeenCalledTimes(1))
    act(() => { hook.result.current.setStyles([entry("<p>v1</p>")]) })

    fetchStylePreviewHtml.mockResolvedValueOnce("<p>v2</p>")
    act(() => { hook.result.current.refreshPreview() })

    await waitFor(() => expect(hook.result.current.previewHtml).toBe("<p>v2</p>"))
    expect(fetchStylePreviewHtml).toHaveBeenLastCalledWith("calm", "tok")
  })

  it("keeps the current preview on screen while a refresh fetches and when it fails", async () => {
    fetchStylePreviewHtml.mockResolvedValueOnce("<p>v1</p>")
    const hook = await openCalm()
    await waitFor(() => expect(hook.result.current.previewHtml).toBe("<p>v1</p>"))

    let finish: (html: string) => void = () => {}
    fetchStylePreviewHtml.mockImplementationOnce(() => new Promise<string>((resolve) => { finish = resolve }))
    act(() => { hook.result.current.refreshPreview() })
    expect(hook.result.current.previewLoading).toBe(false)
    expect(hook.result.current.previewHtml).toBe("<p>v1</p>")

    await act(async () => { finish("") })
    expect(hook.result.current.previewHtml).toBe("<p>v1</p>")
  })
})
