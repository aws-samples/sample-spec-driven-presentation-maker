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

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ""
})

describe("useFollowScroll", () => {
  it("follows the latest changed slide while armed", () => {
    const container = makeScroller()
    const ref = { current: container }
    const { result } = renderHook(() => useFollowScroll(ref))

    act(() => result.current("one"))
    act(() => result.current("two"))

    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 476, behavior: "smooth" })
  })

  it.each([
    ["wheel", () => new WheelEvent("wheel", { bubbles: true })],
    ["touchmove", () => new Event("touchmove", { bubbles: true })],
    ["keydown", () => new KeyboardEvent("keydown", { key: "PageDown", bubbles: true })],
  ])("pauses on %s and re-arms three seconds after the last update", (_name, event) => {
    const container = makeScroller()
    const ref = { current: container }
    const { result } = renderHook(() => useFollowScroll(ref))

    act(() => result.current("one"))
    container.dispatchEvent(event())
    act(() => result.current("two"))
    expect(container.scrollTo).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(2999))
    expect(container.scrollTo).toHaveBeenCalledTimes(1)
    act(() => vi.advanceTimersByTime(1))
    act(() => result.current("two"))
    expect(container.scrollTo).toHaveBeenCalledTimes(2)
  })
})
