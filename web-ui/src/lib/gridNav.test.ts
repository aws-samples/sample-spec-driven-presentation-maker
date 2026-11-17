// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { galleryColumns, gridMove, runSizes, slashPanelWidth } from "./gridNav"

describe("gridMove", () => {
  // Two sections: 5 cards (rows 0-2 / 3-4) then 2 cards (row 5-6), three columns.
  const sizes = [5, 2]

  it("steps left and right through the flat order and stops at the ends", () => {
    expect(gridMove(sizes, 0, "ArrowLeft", 3)).toBe(0)
    expect(gridMove(sizes, 2, "ArrowRight", 3)).toBe(3)
    expect(gridMove(sizes, 6, "ArrowRight", 3)).toBe(6)
  })

  it("keeps the column moving down and takes the last card of a shorter row", () => {
    expect(gridMove(sizes, 1, "ArrowDown", 3)).toBe(4)
    expect(gridMove(sizes, 2, "ArrowDown", 3)).toBe(4)
  })

  it("crosses section boundaries by row, not by flat offset", () => {
    expect(gridMove(sizes, 4, "ArrowDown", 3)).toBe(6)
    expect(gridMove(sizes, 5, "ArrowUp", 3)).toBe(3)
    expect(gridMove(sizes, 6, "ArrowUp", 3)).toBe(4)
  })

  it("stops at the top and bottom rows", () => {
    expect(gridMove(sizes, 1, "ArrowUp", 3)).toBe(1)
    expect(gridMove(sizes, 6, "ArrowDown", 3)).toBe(6)
  })

  it("ignores other keys", () => {
    expect(gridMove(sizes, 1, "Enter", 3)).toBeNull()
  })
})

describe("gallery geometry", () => {
  it("caps the panel at 640px and keeps window margins", () => {
    expect(slashPanelWidth(1440)).toBe(640)
    expect(slashPanelWidth(400)).toBe(376)
  })

  it("fits four compact cards in a full-width panel and fewer as it narrows", () => {
    expect(galleryColumns(640)).toBe(4)
    expect(galleryColumns(480)).toBe(3)
    expect(galleryColumns(376)).toBe(2)
  })

  it("groups consecutive runs", () => {
    expect(runSizes(["t", "t", "s", "f"], (x) => x)).toEqual([2, 1, 1])
    expect(runSizes([], (x) => x)).toEqual([])
  })
})
