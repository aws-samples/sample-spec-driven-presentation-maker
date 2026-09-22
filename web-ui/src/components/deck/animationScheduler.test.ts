// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  acquire,
  advanceTypewriters,
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
    const first = acquire("one").then((release) => { granted.push("one"); return release })
    const second = acquire("two").then((release) => { granted.push("two"); return release })
    const third = acquire("three").then((release) => { granted.push("three"); return release })
    const fourth = acquire("four").then((release) => { granted.push("four"); return release })

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
    const releaseOne = await acquire("one")
    const releaseTwo = await acquire("two")
    const controller = new AbortController()
    const queued = acquire("hidden", controller.signal)

    controller.abort()
    expect(await queued).toBeNull()

    releaseOne!()
    const releaseNext = await acquire("next")
    expect(releaseNext).toBeTypeOf("function")
    releaseTwo!()
    releaseNext!()
  })

  it("advances one character per frame and catches up by at most two after a long frame", () => {
    const first = document.createElement("span")
    const second = document.createElement("span")
    registerTypewriter([
      { el: first, fullText: "abc" },
      { el: second, fullText: "de" },
    ], 20)

    advanceTypewriters(139)
    expect(first.textContent).toBe("a")
    expect(second.textContent).toBe("")

    advanceTypewriters(181)
    expect(first.textContent).toBe("abc")
    expect(second.textContent).toBe("")

    advanceTypewriters(205)
    expect(second.textContent).toBe("d")
    advanceTypewriters(226)
    expect(second.textContent).toBe("de")
  })

  it("writes one character on every animation frame", () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    }))
    const span = document.createElement("span")
    registerTypewriter([{ el: span, fullText: "abcd" }], 15)

    frames.shift()!(116)
    expect(span.textContent).toBe("a")
    frames.shift()!(133)
    expect(span.textContent).toBe("ab")
  })
})
