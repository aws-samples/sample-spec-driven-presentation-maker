// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useFollowScroll } from "./useFollowScroll"

function makeScroller() {
  const container = document.createElement("div")
  Object.defineProperty(container, "scrollTop", { value: 100, writable: true })
  container.scrollTo = vi.fn()
  container.getBoundingClientRect = vi.fn(() => ({ top: 20 } as DOMRect))
  for (const [slug, top] of [["one", 220], ["two", 420]] as const) {
    const slide = document.createElement("div")
    slide.dataset.slideId = slug
    slide.getBoundingClientRect = vi.fn(() => ({ top } as DOMRect))
    container.appendChild(slide)
  }
  document.body.appendChild(container)
  return container
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date("2026-09-22T00:00:00Z"))
})
afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ""
})

describe("useFollowScroll", () => {
  it("attaches manual-navigation listeners when the slides scroller mounts after the brief tab", () => {
    const container = makeScroller()
    const { result, rerender } = renderHook(
      ({ specTab }: { specTab: "brief" | "slides" }) => useFollowScroll(specTab === "slides" ? container : null),
      { initialProps: { specTab: "brief" } as { specTab: "brief" | "slides" } },
    )

    rerender({ specTab: "slides" })
    act(() => result.current("one"))
    container.dispatchEvent(new WheelEvent("wheel", { bubbles: true }))
    act(() => {
      vi.advanceTimersByTime(1)
      result.current("two")
    })

    expect(container.scrollTo).toHaveBeenCalledTimes(1)
  })

  it("follows the latest changed slide while armed", () => {
    const container = makeScroller()
    const { result } = renderHook(() => useFollowScroll(container))

    act(() => result.current("one"))
    act(() => result.current("two"))

    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 476, behavior: "smooth" })
  })

  it.each([
    ["wheel", () => new WheelEvent("wheel", { bubbles: true })],
    ["touchmove", () => new Event("touchmove", { bubbles: true })],
  ])("pauses on %s and re-arms only when a later change arrives after three seconds", (_name, event) => {
    const container = makeScroller()
    const { result } = renderHook(() => useFollowScroll(container))

    act(() => result.current("one"))
    container.dispatchEvent(event())
    act(() => result.current("two"))
    expect(container.scrollTo).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(3000))
    expect(container.scrollTo).toHaveBeenCalledTimes(1)
    act(() => result.current("two"))
    expect(container.scrollTo).toHaveBeenCalledTimes(2)
  })

  it("requires both manual and change quiet periods before a new change re-arms follow", () => {
    const container = makeScroller()
    const { result } = renderHook(() => useFollowScroll(container))

    act(() => result.current("one"))
    container.dispatchEvent(new WheelEvent("wheel"))

    act(() => {
      vi.advanceTimersByTime(2000)
      result.current("two")
    })
    act(() => {
      vi.advanceTimersByTime(1000)
      result.current("one")
    })
    expect(container.scrollTo).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(2000))
    container.dispatchEvent(new WheelEvent("wheel"))
    act(() => {
      vi.advanceTimersByTime(1000)
      result.current("two")
    })
    expect(container.scrollTo).toHaveBeenCalledTimes(1)

    act(() => {
      vi.advanceTimersByTime(3000)
      result.current("one")
    })
    expect(container.scrollTo).toHaveBeenCalledTimes(2)
  })

  it("pauses for document-level navigation keys but ignores editable targets", () => {
    const container = makeScroller()
    const input = document.createElement("input")
    document.body.appendChild(input)
    const { result } = renderHook(() => useFollowScroll(container))

    act(() => result.current("one"))
    const editable = document.createElement("div")
    editable.setAttribute("contenteditable", "true")
    const nested = document.createElement("span")
    editable.appendChild(nested)
    document.body.appendChild(editable)
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }))
    nested.dispatchEvent(new KeyboardEvent("keydown", { key: "PageDown", bubbles: true }))
    act(() => result.current("two"))
    expect(container.scrollTo).toHaveBeenCalledTimes(2)

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "PageDown", bubbles: true }))
    act(() => result.current("one"))
    expect(container.scrollTo).toHaveBeenCalledTimes(2)
  })

  it("treats non-programmatic scroll events as manual", () => {
    const container = makeScroller()
    const { result } = renderHook(() => useFollowScroll(container))

    act(() => result.current("one"))
    container.dispatchEvent(new Event("scroll"))
    act(() => result.current("two"))
    expect(container.scrollTo).toHaveBeenCalledTimes(2)

    container.dispatchEvent(new Event("scrollend"))
    container.dispatchEvent(new Event("scroll"))
    act(() => result.current("one"))
    expect(container.scrollTo).toHaveBeenCalledTimes(2)
  })
})
