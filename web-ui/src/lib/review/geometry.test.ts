// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import {
  clickFrame, moveRect, normalizeDrag, pointToSlide, resizeRect, roundRect, toPercent, withMinSize,
  type SlideSize,
} from "./geometry"

const S: SlideSize = { width: 1920, height: 1080 }

describe("geometry", () => {
  it("toPercent converts slide px to CSS percentages", () => {
    expect(toPercent([192, 108, 960, 540], S)).toEqual({ left: "10%", top: "10%", width: "50%", height: "50%" })
  })

  it("pointToSlide maps screen px to slide px and clamps to the slide", () => {
    const box = { left: 100, top: 50, width: 960, height: 540 }
    expect(pointToSlide(580, 320, box, S)).toEqual([960, 540])
    expect(pointToSlide(0, 0, box, S)).toEqual([0, 0])
    expect(pointToSlide(5000, 5000, box, S)).toEqual([1920, 1080])
  })

  it("normalizeDrag accepts drags in any direction", () => {
    expect(normalizeDrag([300, 400], [100, 100])).toEqual([100, 100, 200, 300])
    expect(normalizeDrag([100, 100], [300, 400])).toEqual([100, 100, 200, 300])
  })

  it("withMinSize grows tiny frames and keeps them inside", () => {
    const [x, y, w, h] = withMinSize([1919, 1079, 1, 1], S)
    expect(w).toBeCloseTo(38.4)
    expect(h).toBeCloseTo(21.6)
    expect(x + w).toBeLessThanOrEqual(1920)
    expect(y + h).toBeLessThanOrEqual(1080)
  })

  it("clickFrame is 9% × 16% of the slide, centred and clamped", () => {
    const [x, y, w, h] = clickFrame([960, 540], S)
    expect(w).toBeCloseTo(172.8)
    expect(h).toBeCloseTo(172.8)
    expect(x).toBeCloseTo(960 - 86.4)
    expect(y).toBeCloseTo(540 - 86.4)
    expect(clickFrame([0, 0], S).slice(0, 2)).toEqual([0, 0])
    const [ex, ey, ew, eh] = clickFrame([1920, 1080], S)
    expect(ex + ew).toBeCloseTo(1920)
    expect(ey + eh).toBeCloseTo(1080)
  })

  it("moveRect keeps the frame inside the slide", () => {
    expect(moveRect([100, 100, 200, 100], -500, -500, S)).toEqual([0, 0, 200, 100])
    expect(moveRect([100, 100, 200, 100], 5000, 5000, S)).toEqual([1720, 980, 200, 100])
    expect(moveRect([100, 100, 200, 100], 10, 20, S)).toEqual([110, 120, 200, 100])
  })

  it("resizeRect moves only the dragged edges and respects bounds and the minimum", () => {
    const r: [number, number, number, number] = [100, 100, 200, 100]
    expect(resizeRect(r, "e", 50, 999, S)).toEqual([100, 100, 250, 100])
    expect(resizeRect(r, "se", 9999, 9999, S)).toEqual([100, 100, 1820, 980])
    expect(resizeRect(r, "nw", -500, -500, S)).toEqual([0, 0, 300, 200])
    const west = resizeRect(r, "w", 500, 0, S)
    expect(west[0]).toBeCloseTo(300 - 38.4)
    expect(west[2]).toBeCloseTo(38.4)
    expect(west[0] + west[2]).toBeCloseTo(300)
    expect(resizeRect(r, "n", 0, 500, S)[3]).toBeCloseTo(21.6)
    expect(resizeRect(r, "s", 0, -500, S)[3]).toBeCloseTo(21.6)
  })

  it("roundRect yields integers inside the slide", () => {
    expect(roundRect([10.4, 20.6, 100.5, 50.2], S)).toEqual([10, 21, 101, 50])
    expect(roundRect([1919.7, 1079.9, 5, 5], S)).toEqual([1919, 1079, 1, 1])
    expect(roundRect([-3, -3, 0.2, 0.2], S)).toEqual([0, 0, 1, 1])
    const [x, , w] = roundRect([1800.6, 0, 119.6, 10], S)
    expect(x + w).toBeLessThanOrEqual(1920)
  })
})
