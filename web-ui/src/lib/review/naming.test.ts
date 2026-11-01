// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { frameName, nameIndex, nextSeq } from "./naming"

describe("frameName / nameIndex", () => {
  it.each([
    [0, "A"], [1, "B"], [25, "Z"], [26, "AA"], [27, "AB"], [51, "AZ"], [52, "BA"], [701, "ZZ"], [702, "AAA"],
  ])("%i ↔ %s", (index, name) => {
    expect(frameName(index)).toBe(name)
    expect(nameIndex(name)).toBe(index)
  })

  it("round-trips the whole 1-3 letter range", () => {
    for (let i = 0; i < 18278; i += 37) expect(nameIndex(frameName(i))).toBe(i)
  })

  it("rejects non-names", () => {
    expect(nameIndex("")).toBe(-1)
    expect(nameIndex("a")).toBe(-1)
    expect(nameIndex("AAAA")).toBe(-1)
    expect(nameIndex("A1")).toBe(-1)
  })

  it("nextSeq continues after the highest name", () => {
    expect(nextSeq([])).toBe(0)
    expect(nextSeq(["A", "C", "B"])).toBe(3)
    expect(nextSeq(["Z", "AA"])).toBe(27)
    expect(nextSeq(["bad"])).toBe(0)
  })
})
