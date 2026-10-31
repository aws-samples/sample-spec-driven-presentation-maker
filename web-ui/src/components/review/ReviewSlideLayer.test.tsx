// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"

const { toastMock } = vi.hoisted(() => ({
  toastMock: Object.assign(vi.fn((..._args: unknown[]) => "toast-1"), { dismiss: vi.fn() }),
}))
vi.mock("sonner", () => ({ toast: toastMock }))
vi.mock("@/services/deckService", () => ({ createReview: vi.fn() }))

import { ReviewProvider, useReview, type ReviewContextValue } from "./ReviewProvider"
import { ReviewSlideLayer } from "./ReviewSlideLayer"
import { ReviewCommentCard } from "./ReviewCommentCard"
import { ReviewKeyboard } from "./ReviewKeyboard"

let api: ReviewContextValue
const setApi = (value: ReviewContextValue | null) => { api = value as ReviewContextValue }
function Capture() {
  setApi(useReview())
  return null
}

// The slide is drawn at 960 × 540 on screen: 1 screen px = 2 slide px.
const BOX = { left: 0, top: 0, right: 960, bottom: 540, width: 960, height: 540, x: 0, y: 0, toJSON: () => ({}) } as DOMRect

function renderLayer() {
  renderWithIntl(
    <ReviewProvider deckId="d1" slugs={["intro"]} enabled agentBusy={false} openChat={() => {}}>
      <Capture />
      <div data-slide-scroller>
        <div data-review-slide="intro" className="relative">
          <ReviewSlideLayer slug="intro" index={0} />
        </div>
      </div>
      <ReviewKeyboard />
      <ReviewCommentCard />
    </ReviewProvider>,
  )
  act(() => { api.setToolOn(true) })
  return document.querySelector<HTMLElement>("[data-review-layer]")!
}

const press = (el: Element, x: number, y: number) => fireEvent.pointerDown(el, { clientX: x, clientY: y, button: 0, pointerId: 1 })
const move = (el: Element, x: number, y: number) => fireEvent.pointerMove(el, { clientX: x, clientY: y, pointerId: 1 })
const release = (el: Element, x: number, y: number) => fireEvent.pointerUp(el, { clientX: x, clientY: y, button: 0, pointerId: 1 })
const editor = () => screen.queryByPlaceholderText(/Describe the change/)

/** Draw frame by dragging and save `text` with Enter. */
function drawAndSave(layer: HTMLElement, text: string) {
  press(layer, 100, 100)
  move(layer, 300, 250)
  release(layer, 300, 250)
  fireEvent.change(editor()!, { target: { value: text } })
  fireEvent.keyDown(editor()!, { key: "Enter" })
}

describe("ReviewSlideLayer", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(BOX)
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it("a drag creates frame A with the editor open", () => {
    const layer = renderLayer()
    press(layer, 100, 100)
    move(layer, 300, 250)
    expect(document.querySelector("[data-review-temp]")).not.toBeNull()
    release(layer, 300, 250)
    expect(api.drafts).toEqual([{ name: "A", slide: "intro", rect: [200, 200, 400, 300], text: "" }])
    expect(document.querySelector('[data-review-frame="A"]')).not.toBeNull()
    expect(editor()).not.toBeNull()
    expect(document.activeElement).toBe(editor())
    expect(document.querySelector("[data-review-temp]")).toBeNull()
  })

  it("a click with nothing selected places a frame centred on the pointer", () => {
    const layer = renderLayer()
    press(layer, 480, 270)
    release(layer, 481, 270)
    expect(api.drafts).toHaveLength(1)
    const [x, y, w, h] = api.drafts[0].rect
    expect(w).toBeCloseTo(1920 * 0.09)
    expect(h).toBeCloseTo(1080 * 0.16)
    expect(x + w / 2).toBeCloseTo(960)
    expect(y + h / 2).toBeCloseTo(540)
  })

  it("a click while a frame is selected only deselects it (R2.1)", () => {
    const layer = renderLayer()
    drawAndSave(layer, "bigger")
    act(() => { api.select("A") })
    press(layer, 800, 400)
    release(layer, 800, 400)
    expect(api.drafts).toHaveLength(1)
    expect(api.selected).toBeNull()
    // Nothing selected or open any more: the next click places a frame (R2.2).
    press(layer, 800, 400)
    release(layer, 800, 400)
    expect(api.drafts.map(d => d.name)).toEqual(["A", "B"])
  })

  it("a click while the editor is open saves and closes it without a new frame", () => {
    const layer = renderLayer()
    press(layer, 100, 100)
    release(layer, 100, 100)
    fireEvent.change(editor()!, { target: { value: "typed" } })
    press(layer, 800, 400)
    release(layer, 800, 400)
    expect(api.drafts.map(d => [d.name, d.text])).toEqual([["A", "typed"]])
    expect(api.editor).toBeNull()
  })

  it("Enter saves the text and closes the card", () => {
    const layer = renderLayer()
    drawAndSave(layer, "  make it bigger ")
    expect(api.drafts[0].text).toBe("make it bigger")
    expect(api.editor).toBeNull()
    expect(api.selected).toBeNull()
  })

  it("Shift+Enter does not save", () => {
    const layer = renderLayer()
    press(layer, 100, 100)
    release(layer, 100, 100)
    fireEvent.change(editor()!, { target: { value: "line" } })
    fireEvent.keyDown(editor()!, { key: "Enter", shiftKey: true })
    expect(api.editor).not.toBeNull()
    expect(api.drafts[0].text).toBe("")
  })

  it("Esc on a new empty frame removes it", () => {
    const layer = renderLayer()
    press(layer, 100, 100)
    release(layer, 100, 100)
    expect(api.drafts).toHaveLength(1)
    fireEvent.keyDown(editor()!, { key: "Escape" })
    expect(api.drafts).toEqual([])
    expect(api.toolOn).toBe(true)
    expect(toastMock).not.toHaveBeenCalled()
  })

  it("Delete removes the selected draft and offers undo", () => {
    const layer = renderLayer()
    drawAndSave(layer, "bigger")
    act(() => { api.select("A") })
    fireEvent.keyDown(window, { key: "Delete" })
    expect(api.drafts).toEqual([])
    expect(toastMock).toHaveBeenCalledWith("Deleted A", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }))
    fireEvent.keyDown(window, { key: "z", metaKey: true })
    expect(api.drafts.map(d => d.name)).toEqual(["A"])
  })

  it("dragging a frame moves it; clicking it opens its card", () => {
    const layer = renderLayer()
    drawAndSave(layer, "bigger")
    const frame = document.querySelector<HTMLElement>('[data-review-frame="A"]')!
    press(frame, 150, 150)
    move(frame, 200, 170)
    release(frame, 200, 170)
    expect(api.drafts[0].rect).toEqual([300, 240, 400, 300])
    expect(api.editor).toBeNull()
    press(frame, 200, 170)
    release(frame, 200, 170)
    expect(api.editor).toEqual({ key: "A", isNew: false })
    expect((editor() as HTMLTextAreaElement).value).toBe("bigger")
  })

  it("the selected draft has 8 resize handles; the se handle resizes", () => {
    const layer = renderLayer()
    drawAndSave(layer, "bigger")
    act(() => { api.select("A") })
    const handles = document.querySelectorAll("[data-handle]")
    expect(handles).toHaveLength(8)
    const se = document.querySelector('[data-handle="se"]')!
    press(se, 300, 250)
    move(se, 350, 260)
    release(se, 350, 260)
    expect(api.drafts[0].rect).toEqual([200, 200, 500, 320])
  })

  it("Esc deselects first, then turns the tool off (R1.4)", () => {
    const layer = renderLayer()
    drawAndSave(layer, "bigger")
    act(() => { api.select("A") })
    fireEvent.keyDown(window, { key: "Escape" })
    expect(api.selected).toBeNull()
    expect(api.toolOn).toBe(true)
    fireEvent.keyDown(window, { key: "Escape" })
    expect(api.toolOn).toBe(false)
  })

  it("@ suggests the other drafts and inserts the chosen name", () => {
    const layer = renderLayer()
    drawAndSave(layer, "sample colour")
    press(layer, 800, 400)
    release(layer, 800, 400)
    const ta = editor() as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: "same as @" } })
    expect(screen.getByRole("listbox")).not.toBeNull()
    expect(screen.getAllByRole("option")).toHaveLength(1)
    fireEvent.keyDown(ta, { key: "Enter" })
    expect(ta.value).toBe("same as @A ")
    fireEvent.keyDown(ta, { key: "Enter" })
    expect(api.drafts[1].text).toBe("same as @A")
  })
})
