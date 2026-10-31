// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { exceedsClickTolerance, exceedsFrameDragTolerance, isTypingTarget, resolveBackgroundRelease } from "./interaction"

const S = { width: 1920, height: 1080 }

describe("resolveBackgroundRelease (R2.1 / R2.2)", () => {
  it.each([
    [true, true, "draw"],
    [true, false, "draw"],
    [false, true, "confirm"],
    [false, false, "place"],
  ] as const)("moved=%s editingAtDown=%s → %s", (moved, editingAtDown, expected) => {
    expect(resolveBackgroundRelease({ moved, editingAtDown })).toBe(expected)
  })
})

describe("tolerances", () => {
  it("a background press within 1.2% of the slide is a click", () => {
    expect(exceedsClickTolerance([100, 100], [120, 110], S)).toBe(false)
    expect(exceedsClickTolerance([100, 100], [124, 100], S)).toBe(true)
    expect(exceedsClickTolerance([100, 100], [100, 114], S)).toBe(true)
  })

  it("a press on a frame moving less than 0.4% is a click", () => {
    expect(exceedsFrameDragTolerance(3, 1, S)).toBe(false)
    expect(exceedsFrameDragTolerance(8, 1, S)).toBe(true)
  })
})

describe("isTypingTarget", () => {
  it("detects text fields and editable content", () => {
    const input = document.createElement("input")
    const textarea = document.createElement("textarea")
    const div = document.createElement("div")
    const editable = document.createElement("div")
    editable.setAttribute("contenteditable", "true")
    const child = document.createElement("span")
    editable.appendChild(child)
    expect(isTypingTarget(input)).toBe(true)
    expect(isTypingTarget(textarea)).toBe(true)
    expect(isTypingTarget(div)).toBe(false)
    expect(isTypingTarget(child)).toBe(true)
    expect(isTypingTarget(null)).toBe(false)
  })
})
