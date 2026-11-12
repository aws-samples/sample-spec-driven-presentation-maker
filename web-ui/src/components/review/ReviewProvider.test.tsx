// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"

const { toastMock, createReview } = vi.hoisted(() => {
  const toastMock = Object.assign(vi.fn<(...args: unknown[]) => string>(() => "toast-1"), { dismiss: vi.fn() })
  return { toastMock, createReview: vi.fn() }
})
vi.mock("sonner", () => ({ toast: toastMock }))
vi.mock("@/services/deckService", () => ({ createReview }))

import { ReviewProvider, useReview, type ReviewContextValue, type SubmittedReview } from "./ReviewProvider"

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

  it("a frame stays without a comment; only Esc on a frame just drawn cancels it", () => {
    renderProvider()
    act(() => { api.addFrame("intro", [0, 0, 100, 100]) })
    act(() => { api.closeEditor(true) })
    expect(api.drafts.map(d => [d.name, d.text])).toEqual([["A", ""]])
    expect(api.readyDrafts).toHaveLength(1)

    // Esc (cancel) on a new frame removes it without undo, even with typed text.
    act(() => { api.addFrame("intro", [0, 0, 100, 100]) })
    act(() => { api.setEditorText("typed") })
    act(() => { api.closeEditor(false) })
    expect(api.drafts.map(d => d.name)).toEqual(["A"])
    expect(api.canUndo).toBe(false)

    // Emptying a saved comment keeps the frame; cancelling an existing frame keeps it.
    addSaved("intro", "keep")
    act(() => { api.openEditor("C") })
    act(() => { api.setEditorText("   ") })
    act(() => { api.closeEditor(true) })
    act(() => { api.openEditor("A") })
    act(() => { api.closeEditor(false) })
    expect(api.drafts.map(d => [d.name, d.text])).toEqual([["A", ""], ["C", ""]])
    expect(toastMock).not.toHaveBeenCalled()
  })

  it("strips the whitespace the servers strip (U+001C, U+0085) from a comment", () => {
    renderProvider()
    addSaved("intro", "\u001c\u0085 ")
    expect(api.drafts.map(d => d.text)).toEqual([""])
  })

  it("can submit with a comment or a note, not with frames alone", async () => {
    renderProvider()
    expect(api.canSubmit("note")).toBe(false)
    addSaved("intro", "")
    expect(api.canSubmit("")).toBe(false)
    expect(api.canSubmit(" \u0085")).toBe(false)
    expect(api.canSubmit("overall")).toBe(true)
    await act(async () => { await expect(api.submit("")).rejects.toThrow() })
    expect(createReview).not.toHaveBeenCalled()
    expect(api.drafts).toHaveLength(1)
    addSaved("sales", "bigger")
    expect(api.canSubmit("")).toBe(true)
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
    addSaved("intro", "\u0085 bigger \u001c")
    addSaved("sales", "@A colour")
    addSaved("gone", "slide was deleted")
    addSaved("sales", "")
    let created: SubmittedReview | null = null
    await act(async () => { created = await api.submit("\u001f overall note \u0085") })
    expect(created).toMatchObject({ id: "20261101-102000-a1b2", message: "[review:20261101-102000-a1b2] …" })
    expect(createReview).toHaveBeenCalledWith("d1", {
      note: "overall note",
      comments: [
        { name: "A", slide: "intro", rect: [10, 21, 300, 201], text: "bigger" },
        { name: "B", slide: "sales", rect: [10, 21, 300, 201], text: "@A colour" },
        { name: "D", slide: "sales", rect: [10, 21, 300, 201], text: "" },
      ],
    }, "tok")
    // The sent frames leave the canvas at once.
    expect(api.drafts).toEqual([])
    expect(api.toolOn).toBe(false)
    expect(addSaved("intro", "after")).toBe("E")
  })

  it("restore puts the sent frames back in front of frames drawn since, once", async () => {
    createReview.mockResolvedValue({ id: "20261101-102000-a1b2", message: "m" })
    renderProvider()
    addSaved("intro", "first")
    addSaved("sales", "second")
    let created: SubmittedReview | null = null
    await act(async () => { created = await api.submit("") })
    addSaved("intro", "drawn while sending")
    act(() => { created!.restore() })
    expect(api.drafts.map(d => [d.name, d.text])).toEqual([["A", "first"], ["B", "second"], ["C", "drawn while sending"]])
    expect(api.drafts[0].rect).toEqual([10.4, 20.6, 300.2, 200.7])
    act(() => { created!.restore() })
    expect(api.drafts).toHaveLength(3)
    expect(api.readyDrafts).toHaveLength(3)
  })

  it("restore writes the frames back to their deck's drafts when another deck is open", async () => {
    createReview.mockResolvedValue({ id: "20261101-102000-a1b2", message: "m" })
    const { rerender } = renderProvider()
    addSaved("intro", "first")
    let created: SubmittedReview | null = null
    await act(async () => { created = await api.submit("") })
    const other = (deckId: string) => (
      <ReviewProvider deckId={deckId} slugs={["intro", "sales"]} enabled agentBusy={false} openChat={openChat}>
        <Capture />
      </ReviewProvider>
    )
    rerender(other("d2"))
    act(() => { created!.restore() })
    expect(api.drafts).toEqual([])
    rerender(other("d1"))
    expect(api.drafts.map(d => d.text)).toEqual(["first"])
  })

  it("submit builds the request with createRequest when given, not through the API", async () => {
    const createRequest = vi.fn().mockResolvedValue({ id: "20261112-213600-c0de", message: "[review:20261112-213600-c0de] style" })
    renderProvider({ deckId: "style:brand-blue", slugs: ["1", "2"], createRequest })
    addSaved("2", "bigger")
    let created: SubmittedReview | null = null
    await act(async () => { created = await api.submit("note") })
    expect(createRequest).toHaveBeenCalledWith({
      note: "note",
      comments: [{ name: "A", slide: "2", rect: [10, 21, 300, 201], text: "bigger" }],
    })
    expect(createReview).not.toHaveBeenCalled()
    expect(created).toMatchObject({ id: "20261112-213600-c0de", message: "[review:20261112-213600-c0de] style" })
    expect(api.drafts).toEqual([])
  })

  it("submit failure keeps the drafts", async () => {
    createReview.mockRejectedValue(new Error("boom"))
    renderProvider()
    addSaved("intro", "keep me")
    await act(async () => { await expect(api.submit("")).rejects.toThrow("boom") })
    expect(api.drafts.map(d => d.text)).toEqual(["keep me"])
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
