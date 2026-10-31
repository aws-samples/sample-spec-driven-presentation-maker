// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, expect, it } from "vitest"
import { buildReviewMarker, parseReviewMarkers, stripReviewMarkers } from "./marker"

const ID = "20261101-102000-a1b2"

describe("review marker", () => {
  it("builds and parses a marker", () => {
    expect(buildReviewMarker(ID)).toBe("[review:20261101-102000-a1b2]")
    expect(parseReviewMarkers(`直して\n\n${buildReviewMarker(ID)}`)).toEqual([ID])
  })

  it("returns every marker once, in order", () => {
    const other = "20261102-000000-ffff"
    expect(parseReviewMarkers(`[review:${other}] a [review:${ID}] b [review:${other}]`)).toEqual([other, ID])
  })

  it("ignores malformed ids", () => {
    expect(parseReviewMarkers("[review:../x] [review:20261101-102000-A1B2] [review:2026-1]")).toEqual([])
  })

  it("strips markers and surrounding whitespace", () => {
    expect(stripReviewMarkers(`直して\n\n[review:${ID}]`)).toBe("直して")
    expect(stripReviewMarkers(`[review:${ID}]`)).toBe("")
    expect(stripReviewMarkers("[review:bad] keep")).toBe("[review:bad] keep")
  })
})
