// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  acquire,
  advanceTypewriters,
  typewritersForTests as typewriters,
  registerTypewriter,
  resetAnimationSchedulerForTests,
} from "./animationScheduler"

beforeEach(() => {
  resetAnimationSchedulerForTests()
  vi.spyOn(performance, "now").mockReturnValue(100)
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1))
  vi.stubGlobal("cancelAnimationFrame", vi.fn())
})

afterEach(() => {
  resetAnimationSchedulerForTests()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("animation scheduler", () => {
  it("caps concurrency at two and grants queued slides FIFO", async () => {
    const granted: string[] = []
    const first = acquire().then((release) => { granted.push("one"); return release })
    const second = acquire().then((release) => { granted.push("two"); return release })
    const third = acquire().then((release) => { granted.push("three"); return release })
    const fourth = acquire().then((release) => { granted.push("four"); return release })

    const releaseOne = await first
    const releaseTwo = await second
    await Promise.resolve()
    expect(granted).toEqual(["one", "two"])

    releaseOne!()
    const releaseThree = await third
    expect(granted).toEqual(["one", "two", "three"])

    releaseTwo!()
    const releaseFour = await fourth
    expect(granted).toEqual(["one", "two", "three", "four"])
    releaseThree!()
    releaseFour!()
  })

  it("removes an aborted waiter from the queue", async () => {
    const releaseOne = await acquire()
    const releaseTwo = await acquire()
    const controller = new AbortController()
    const queued = acquire(controller.signal)

    controller.abort()
    expect(await queued).toBeNull()

    releaseOne!()
    const releaseNext = await acquire()
    expect(releaseNext).toBeTypeOf("function")
    releaseTwo!()
    releaseNext!()
  })

  it("tracks the elapsed-time cadence within one character at 60 Hz and 120 Hz", () => {
    const text = "x".repeat(60)
    for (const frameMs of [1000 / 60, 1000 / 120]) {
      typewriters.clear()
      const span = document.createElement("span")
      const startedAt = performance.now()
      registerTypewriter([{ el: span, fullText: text }], 15)
      for (let t = startedAt + frameMs; t <= startedAt + 800; t += frameMs) {
        advanceTypewriters(t)
        const target = Math.min(text.length, Math.floor((t - startedAt) / 15))
        expect(Math.abs((span.textContent?.length ?? 0) - target)).toBeLessThanOrEqual(1)
      }
      // The original setInterval(15) showed 53 characters after 800 ms.
      expect(span.textContent?.length).toBeGreaterThanOrEqual(52)
    }
  })

  it("caps catch-up at two characters after a stalled frame", () => {
    const span = document.createElement("span")
    const startedAt = performance.now()
    registerTypewriter([{ el: span, fullText: "abcdefghijklmnop" }], 15)
    advanceTypewriters(startedAt + 16)
    expect(span.textContent).toBe("a")
    advanceTypewriters(startedAt + 216) // 200 ms stall: target is 14, show only 2 more
    expect(span.textContent).toBe("abc")
    advanceTypewriters(startedAt + 232)
    expect(span.textContent).toBe("abcde")
  })
})
