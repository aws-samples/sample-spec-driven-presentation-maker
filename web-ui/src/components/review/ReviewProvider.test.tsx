// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { ReviewRequest } from "@/lib/review/schema"

const { toastMock, createReview, getReview } = vi.hoisted(() => {
  const toastMock = Object.assign(vi.fn((..._args: unknown[]) => "toast-1"), { dismiss: vi.fn() })
  return { toastMock, createReview: vi.fn(), getReview: vi.fn() }
})
vi.mock("sonner", () => ({ toast: toastMock }))
vi.mock("@/services/deckService", () => ({ createReview, getReview }))

import { ReviewProvider, useReview, type ReviewContextValue } from "./ReviewProvider"

let api: ReviewContextValue
const setApi = (value: ReviewContextValue | null) => { api = value as ReviewContextValue }
function Capture() {
  setApi(useReview())
  return null
}

const openChat = vi.fn()

function renderProvider(props: Partial<React.ComponentProps<typeof ReviewProvider>> = {}) {
  return renderWithIntl(
    <ReviewProvider deckId="d1" slugs={["intro", "sales"]} enabled agentBusy={false} openChat={openChat} idToken="tok" {...props}>
      <Capture />
    </ReviewProvider>,
  )
}

function request(id: string, names: string[], status: "open" | "done" = "open"): ReviewRequest {
  return {
    version: 1, id, created_at: "2026-11-01T10:20:00Z", note: null, slide_size: [1920, 1080],
    comments: names.map(name => ({ name, slide: "intro", rect: [0, 0, 100, 100], text: `fix ${name}`, refs: [], status, reply: null })),
  }
}

/** Draw a frame and save its text, as the canvas and card do. */
function addSaved(slide: string, text: string, rect: [number, number, number, number] = [10.4, 20.6, 300.2, 200.7]) {
  let name = ""
  act(() => { name = api.addFrame(slide, rect) })
  act(() => { api.setEditorText(text) })
  act(() => { api.closeEditor(true) })
  return name
}

describe("ReviewProvider", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it("useReview is null without a provider", () => {
    renderWithIntl(<Capture />)
    expect(api).toBeNull()
  })

  it("names frames in sequence, opens the editor, and opens the chat on the first frame", () => {
    renderProvider()
    let a = ""
    act(() => { a = api.addFrame("intro", [0, 0, 100, 100]) })
    expect(a).toBe("A")
    expect(api.editor).toEqual({ key: "A", isNew: true })
    expect(api.selected).toBe("A")
    expect(api.hintSeen).toBe(true)
    expect(openChat).toHaveBeenCalledTimes(1)
    act(() => { api.setEditorText("x"); api.closeEditor(true) })
    expect(addSaved("sales", "y")).toBe("B")
    expect(openChat).toHaveBeenCalledTimes(1)
  })

  it("keeps drafts across a remount (localStorage per deck)", () => {
    const { unmount } = renderProvider()
    addSaved("intro", "make the logo smaller")
    unmount()
    renderProvider()
    expect(api.drafts.map(d => [d.name, d.text])).toEqual([["A", "make the logo smaller"]])
    expect(addSaved("intro", "next")).toBe("B")
    cleanup()
    renderProvider({ deckId: "d2" })
    expect(api.drafts).toEqual([])
  })

  it("a comment is required: an empty new frame goes without undo, an emptied one is deleted with undo (R2.6)", () => {
    renderProvider()
    act(() => { api.addFrame("intro", [0, 0, 100, 100]) })
    act(() => { api.closeEditor(true) })
    expect(api.drafts).toEqual([])
    expect(api.canUndo).toBe(false)
    expect(toastMock).not.toHaveBeenCalled()

    addSaved("intro", "keep")
    act(() => { api.openEditor("B") })
    act(() => { api.setEditorText("   ") })
    act(() => { api.closeEditor(true) })
    expect(api.drafts).toEqual([])
    expect(api.canUndo).toBe(true)
    expect(toastMock).toHaveBeenCalledTimes(1)
  })

  it("cancel keeps the saved text", () => {
    renderProvider()
    addSaved("intro", "original")
    act(() => { api.openEditor("A") })
    act(() => { api.setEditorText("changed") })
    act(() => { api.closeEditor(false) })
    expect(api.drafts[0].text).toBe("original")
  })

  it("delete names the drafts that reference it, and undo restores the frame in place (R2.7)", () => {
    renderProvider()
    addSaved("intro", "first")
    addSaved("intro", "same colour as @A")
    addSaved("sales", "third")
    act(() => { api.deleteFrame("A") })
    expect(api.drafts.map(d => d.name)).toEqual(["B", "C"])
    const [message, options] = toastMock.mock.calls[0] as [string, { action: { label: string; onClick: () => void }; duration: number }]
    expect(message).toBe("Deleted A (referenced by B)")
    expect(options.action.label).toBe("Undo")
    expect(options.duration).toBe(5000)
    act(() => { options.action.onClick() })
    expect(api.drafts.map(d => d.name)).toEqual(["A", "B", "C"])
    expect(api.selected).toBe("A")
    expect(api.canUndo).toBe(false)
  })

  it("submit sends integer rects, clears the drafts, keeps the sequence and turns the tool off", async () => {
    createReview.mockResolvedValue(request("20261101-102000-a1b2", ["A", "B"]))
    renderProvider()
    act(() => { api.setToolOn(true) })
    addSaved("intro", "  bigger  ")
    addSaved("sales", "@A colour")
    addSaved("gone", "slide was deleted")
    let id = ""
    await act(async () => { id = await api.submit("  overall note ") })
    expect(id).toBe("20261101-102000-a1b2")
    expect(createReview).toHaveBeenCalledWith("d1", {
      note: "overall note",
      comments: [
        { name: "A", slide: "intro", rect: [10, 21, 300, 201], text: "bigger" },
        { name: "B", slide: "sales", rect: [10, 21, 300, 201], text: "@A colour" },
      ],
    }, "tok")
    expect(api.drafts).toEqual([])
    expect(api.toolOn).toBe(false)
    expect(api.requests.get(id)).toMatchObject({ id })
    expect(api.openSent.map(f => f.key)).toEqual([`${id}/A`, `${id}/B`])
    expect(addSaved("intro", "after")).toBe("D")
  })

  it("submit failure keeps the drafts", async () => {
    createReview.mockRejectedValue(new Error("boom"))
    renderProvider()
    addSaved("intro", "keep me")
    await act(async () => { await expect(api.submit("")).rejects.toThrow("boom") })
    expect(api.drafts.map(d => d.text)).toEqual(["keep me"])
  })

  it("track loads requests once and continues the sequence after their names", async () => {
    getReview.mockResolvedValue(request("20261101-102000-a1b2", ["A", "B", "C"]))
    renderProvider()
    await act(async () => { api.track("d1", ["20261101-102000-a1b2", "20261101-102000-a1b2", "bad id"]) })
    await act(async () => {})
    expect(getReview).toHaveBeenCalledTimes(1)
    expect(getReview).toHaveBeenCalledWith("d1", "20261101-102000-a1b2", "tok")
    expect(api.openSent).toHaveLength(3)
    act(() => { api.track("other-deck", ["20261101-102001-0000"]) })
    expect(getReview).toHaveBeenCalledTimes(1)
    expect(addSaved("intro", "x")).toBe("D")
  })

  it("an unreadable request is marked as an error", async () => {
    getReview.mockResolvedValue(null)
    renderProvider()
    await act(async () => { api.track("d1", ["20261101-102000-a1b2"]) })
    await act(async () => {})
    expect(api.requests.get("20261101-102000-a1b2")).toBe("error")
  })

  it("refresh re-reads only requests with open comments, at most every 1.5 s", async () => {
    vi.useFakeTimers()
    try {
      getReview.mockImplementation(async (_d: string, id: string) => request(id, ["A"], id.endsWith("0000") ? "done" : "open"))
      renderProvider()
      await act(async () => { api.track("d1", ["20261101-102000-0000", "20261101-102000-1111"]) })
      expect(getReview).toHaveBeenCalledTimes(2)
      await act(async () => { api.refresh() })
      expect(getReview).toHaveBeenCalledTimes(3)
      expect(getReview).toHaveBeenLastCalledWith("d1", "20261101-102000-1111", "tok")
      await act(async () => { api.refresh(); api.refresh() })
      expect(getReview).toHaveBeenCalledTimes(3)
      await act(async () => { vi.advanceTimersByTime(1600) })
      expect(getReview).toHaveBeenCalledTimes(4)
    } finally {
      vi.useRealTimers()
    }
  })

  it("statusOf shows 対応中 for the latest request only while the agent works", async () => {
    getReview.mockImplementation(async (_d: string, id: string) => request(id, ["A"]))
    const { rerender } = renderProvider({ agentBusy: true })
    await act(async () => { api.track("d1", ["20261101-102000-a1b2", "20261102-090000-ffff"]) })
    expect(api.latestRequestId).toBe("20261102-090000-ffff")
    expect(api.statusOf("20261102-090000-ffff")).toBe("working")
    expect(api.statusOf("20261101-102000-a1b2")).toBe("sent")
    rerender(
      <ReviewProvider deckId="d1" slugs={["intro", "sales"]} enabled agentBusy={false} openChat={openChat}>
        <Capture />
      </ReviewProvider>,
    )
    expect(api.statusOf("20261102-090000-ffff")).toBe("sent")
  })

  it("changing deck resets the tool and selection", () => {
    const { rerender } = renderProvider()
    act(() => { api.setToolOn(true) })
    addSaved("intro", "x")
    act(() => { api.select("A") })
    rerender(
      <ReviewProvider deckId="d2" slugs={["intro"]} enabled agentBusy={false} openChat={openChat}>
        <Capture />
      </ReviewProvider>,
    )
    expect(api.toolOn).toBe(false)
    expect(api.selected).toBeNull()
    expect(api.drafts).toEqual([])
  })
})
