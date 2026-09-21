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

    releaseOne()
    const releaseThree = await third
    expect(granted).toEqual(["one", "two", "three"])

    releaseTwo()
    const releaseFour = await fourth
    expect(granted).toEqual(["one", "two", "three", "four"])
    releaseThree()
    releaseFour()
  })

  it("advances all registered spans from elapsed time", () => {
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
    expect(second.textContent).toBe("d")

    advanceTypewriters(205)
    expect(second.textContent).toBe("de")
  })
})
