// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { cn, formatDate, meshGradient } from "./utils"

describe("cn", () => {
  it("merges tailwind classes with later overrides", () => {
    expect(cn("p-2", "p-4")).toBe("p-4")
  })
})

describe("formatDate", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-07-07T12:00:00Z"))
  })
  afterEach(() => vi.useRealTimers())

  it("returns empty string for empty input", () => {
    expect(formatDate("")).toBe("")
  })

  it("formats today as Today", () => {
    expect(formatDate("2026-07-07T09:00:00Z")).toBe("Today")
  })

  it("formats one day ago as Yesterday", () => {
    expect(formatDate("2026-07-06T09:00:00Z")).toBe("Yesterday")
  })

  it("formats within a week as Nd ago", () => {
    expect(formatDate("2026-07-04T09:00:00Z")).toBe("3d ago")
  })

  it("formats older dates as month + day", () => {
    expect(formatDate("2026-02-14T09:00:00Z")).toMatch(/Feb 14/)
  })
})

describe("meshGradient", () => {
  it("is deterministic for the same id", () => {
    expect(meshGradient("deck-abc")).toBe(meshGradient("deck-abc"))
  })

  it("differs across ids with different seeds", () => {
    expect(meshGradient("aaaa")).not.toBe(meshGradient("zzzz"))
  })

  it("produces layered CSS gradients", () => {
    const css = meshGradient("deck-abc")
    expect(css).toContain("radial-gradient")
    expect(css).toContain("linear-gradient")
  })
})
