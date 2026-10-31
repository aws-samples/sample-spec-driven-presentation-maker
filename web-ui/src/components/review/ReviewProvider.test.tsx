// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { SentReview } from "@/lib/review/marker"

const { toastMock, createReview } = vi.hoisted(() => {
  const toastMock = Object.assign(vi.fn((..._args: unknown[]) => "toast-1"), { dismiss: vi.fn() })
  return { toastMock, createReview: vi.fn() }
})
vi.mock("sonner", () => ({ toast: toastMock }))
vi.mock("@/services/deckService", () => ({ createReview }))

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

function sent(id: string, names: string[], slide = "intro"): SentReview {
  return { id, note: null, comments: names.map(name => ({ name, slide, rect: [0, 0, 100, 100], text: `fix ${name}` })) }
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
    createReview.mockResolvedValue({ id: "20261101-102000-a1b2", message: "[review:20261101-102000-a1b2] …" })
    renderProvider()
    act(() => { api.setToolOn(true) })
    addSaved("intro", "  bigger  ")
    addSaved("sales", "@A colour")
    addSaved("gone", "slide was deleted")
    let created = { id: "", message: "" }
    await act(async () => { created = await api.submit("  overall note ") })
    expect(created).toEqual({ id: "20261101-102000-a1b2", message: "[review:20261101-102000-a1b2] …" })
    expect(createReview).toHaveBeenCalledWith("d1", {
      note: "overall note",
      comments: [
        { name: "A", slide: "intro", rect: [10, 21, 300, 201], text: "bigger" },
        { name: "B", slide: "sales", rect: [10, 21, 300, 201], text: "@A colour" },
      ],
    }, "tok")
    expect(api.drafts).toEqual([])
    expect(api.toolOn).toBe(false)
    // The frames come back from the chat message while its turn runs (setWorkingReview).
    expect(api.openSent).toEqual([])
    expect(addSaved("intro", "after")).toBe("D")
  })

  it("submit failure keeps the drafts", async () => {
    createReview.mockRejectedValue(new Error("boom"))
    renderProvider()
    addSaved("intro", "keep me")
    await act(async () => { await expect(api.submit("")).rejects.toThrow("boom") })
    expect(api.drafts.map(d => d.text)).toEqual(["keep me"])
  })

  it("shows the working request's frames on existing slides until the turn ends", () => {
    renderProvider()
    const id = "20261101-102000-a1b2"
    const review = { ...sent(id, ["A"]), comments: [...sent(id, ["A"]).comments, ...sent(id, ["B"], "gone").comments] }
    act(() => { api.setWorkingReview("d1", review) })
    expect(api.workingReview).toBe(review)
    expect(api.openSent).toEqual([{ key: `${id}/A`, requestId: id, name: "A", slide: "intro", rect: [0, 0, 100, 100], size: { width: 1920, height: 1080 }, text: "fix A" }])
    expect(api.lookup(`${id}/A`)?.kind).toBe("sent")
    act(() => { api.select(`${id}/A`); api.setPeek(`${id}/A`) })
    act(() => { api.setWorkingReview("d1", null) })
    expect(api.openSent).toEqual([])
    expect(api.selected).toBeNull()
    expect(api.peek).toBeNull()
  })

  it("ignores a working request reported for another deck", () => {
    renderProvider()
    act(() => { api.setWorkingReview("d2", sent("20261101-102000-a1b2", ["A"])) })
    expect(api.workingReview).toBeNull()
    expect(api.openSent).toEqual([])
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
