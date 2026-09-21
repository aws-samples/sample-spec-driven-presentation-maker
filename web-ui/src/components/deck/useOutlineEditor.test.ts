// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { act, renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { getSubItemText, type SlideNode } from "./outlineDocument"
import { useOutlineEditor } from "./useOutlineEditor"

const BASE = [
  "# Deck",
  "",
  "## Opening",
  "",
  "- [one] First claim",
  "  - body: First body",
  "",
  "- [two] Second claim",
  "  - visual: Chart",
  "",
].join("\n")

const slides = (doc: ReturnType<typeof useOutlineEditor>["doc"]) =>
  doc.nodes.filter((node): node is SlideNode => node.type === "slide")

describe("useOutlineEditor", () => {
  it("tracks text edits as one history step committed from focus to blur", () => {
    const { result } = renderHook(() => useOutlineEditor(BASE))
    const first = slides(result.current.doc)[0]
    let before = result.current.snapshot()

    act(() => result.current.updateSubItem(first.id, "body", "Edited line one\nEdited line two"))
    expect(result.current.dirty).toBe(true)
    expect(result.current.stats).toEqual({ added: 2, deleted: 1 })
    expect(result.current.canUndo).toBe(false)

    act(() => result.current.commitSnapshot(before))
    expect(result.current.canUndo).toBe(true)
    act(() => result.current.undo())
    expect(getSubItemText(slides(result.current.doc)[0], "body")).toBe("First body")
    act(() => result.current.redo())
    expect(getSubItemText(slides(result.current.doc)[0], "body")).toBe("Edited line one\nEdited line two")

    before = result.current.snapshot()
    act(() => result.current.updateSubItem(first.id, "body", "Edited line one\nEdited line two"))
    act(() => result.current.commitSnapshot(before))
    expect(result.current.canUndo).toBe(true)
  })

  it("accepts live content while clean and freezes the local document while dirty", () => {
    const { result, rerender } = renderHook(({ content }) => useOutlineEditor(content), {
      initialProps: { content: BASE },
    })
    const cleanUpdate = BASE.replace("First claim", "Agent clean update")
    rerender({ content: cleanUpdate })
    expect(slides(result.current.doc)[0].message).toBe("Agent clean update")
    expect(result.current.base).toBe(cleanUpdate)

    const before = result.current.snapshot()
    act(() => result.current.updateSlideMessage(slides(result.current.doc)[0].id, "My local edit"))
    act(() => result.current.commitSnapshot(before))
    const laterUpdate = cleanUpdate.replace("Second claim", "Agent later update")
    rerender({ content: laterUpdate })
    expect(slides(result.current.doc)[0].message).toBe("My local edit")
    expect(slides(result.current.doc)[1].message).toBe("Second claim")
    expect(result.current.latestSeen).toBe(laterUpdate)

    act(() => result.current.discard())
    expect(slides(result.current.doc)[1].message).toBe("Agent later update")
    expect(result.current.base).toBe(laterUpdate)
    expect(result.current.dirty).toBe(false)
  })

  it("adds, duplicates, deletes, undoes, and redoes slides", () => {
    const { result } = renderHook(() => useOutlineEditor(BASE))
    const section = result.current.doc.nodes.find((node) => node.type === "section")!
    let addedId = ""
    act(() => { addedId = result.current.addSlide(section.id) })
    expect(slides(result.current.doc).map((slide) => slide.slug)).toEqual(["one", "two", "slide-3"])

    let copyId = ""
    act(() => { copyId = result.current.duplicateSlide(addedId) })
    expect(slides(result.current.doc).map((slide) => slide.slug)).toContain("slide-3-copy")

    act(() => { result.current.deleteSlide(copyId) })
    expect(slides(result.current.doc).map((slide) => slide.slug)).not.toContain("slide-3-copy")
    act(() => result.current.undo())
    expect(slides(result.current.doc).map((slide) => slide.slug)).toContain("slide-3-copy")
    act(() => result.current.redo())
    expect(slides(result.current.doc).map((slide) => slide.slug)).not.toContain("slide-3-copy")
  })

  it("nudges slides across chapter boundaries", () => {
    const content = `${BASE}## Decision\n\n- [three] Third claim\n`
    const { result } = renderHook(() => useOutlineEditor(content))
    const second = slides(result.current.doc)[1]
    act(() => { expect(result.current.nudgeSlide(second.id, 1)).toBe(true) })
    expect(slides(result.current.doc).map((slide) => slide.slug)).toEqual(["one", "three", "two"])
    act(() => result.current.undo())
    expect(slides(result.current.doc).map((slide) => slide.slug)).toEqual(["one", "two", "three"])
  })
})
