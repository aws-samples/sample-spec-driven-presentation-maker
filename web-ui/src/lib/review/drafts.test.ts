// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { draftsKey, loadDrafts, saveDrafts, type DraftState } from "./drafts"
import { frameName } from "./naming"

const frame = (name: string, text = "make it bigger") => ({ name, slide: "intro", rect: [10, 20, 300, 200] as [number, number, number, number], text })

describe("drafts storage", () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it("round-trips per deck", () => {
    const state: DraftState = { seq: 2, frames: [frame("A"), frame("B", "@A と同じ色")] }
    saveDrafts("d1", state)
    expect(JSON.parse(localStorage.getItem("sdpm-review-drafts:d1")!)).toEqual({ v: 1, ...state })
    expect(loadDrafts("d1")).toEqual(state)
    expect(loadDrafts("d2")).toEqual({ seq: 0, frames: [] })
    expect(draftsKey("d1")).toBe("sdpm-review-drafts:d1")
  })

  it("drops corrupted or foreign values", () => {
    for (const raw of ["{not json", "[]", '{"v":2,"seq":1,"frames":[]}', '{"v":1,"seq":1,"frames":{}}',
      '{"v":1,"seq":1,"frames":[{"name":"a","slide":"x","rect":[0,0,1,1],"text":"t"}]}',
      '{"v":1,"seq":1,"frames":[{"name":"A","slide":"x","rect":[0,0,1],"text":"t"}]}']) {
      localStorage.setItem("sdpm-review-drafts:d1", raw)
      expect(loadDrafts("d1")).toEqual({ seq: 0, frames: [] })
    }
  })

  it("drops frames whose comment is empty", () => {
    localStorage.setItem("sdpm-review-drafts:d1", JSON.stringify({ v: 1, seq: 3, frames: [frame("A"), frame("C", "  ")] }))
    expect(loadDrafts("d1")).toEqual({ seq: 3, frames: [frame("A")] })
  })

  it("seq never falls behind a stored name, so deleted names are not reused", () => {
    localStorage.setItem("sdpm-review-drafts:d1", JSON.stringify({ v: 1, seq: 0, frames: [frame("C")] }))
    expect(loadDrafts("d1").seq).toBe(3)
    // A, B deleted after C was drawn: seq stays 3, the next name is D
    saveDrafts("d1", { seq: 3, frames: [] })
    expect(frameName(loadDrafts("d1").seq)).toBe("D")
  })

  it("never throws on storage errors", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError") })
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("denied", "SecurityError") })
    expect(() => saveDrafts("d1", { seq: 1, frames: [frame("A")] })).not.toThrow()
    expect(loadDrafts("d1")).toEqual({ seq: 0, frames: [] })
  })
})
