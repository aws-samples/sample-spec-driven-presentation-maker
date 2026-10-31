// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Review request contract — the same fixture as tests/test_review_schema.py, so the
 * Python validator (Cloud) and this one (Local) accept and reject the same submissions.
 */

import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"
import {
  buildReviewFile, createdAtIso, extractRefs, isReviewId, newReviewId, parseReviewFile, validateReviewSubmission,
} from "./schema"

interface Fixture {
  slide_size: [number, number]
  slugs: string[]
  cases: { name: string; body: unknown; valid: boolean }[]
}

const fixture = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../tests/fixtures/review_submissions.json"), "utf-8"),
) as Fixture
const slugs = new Set(fixture.slugs)

describe("validateReviewSubmission", () => {
  it("has the shared fixture", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(20)
  })

  it.each(fixture.cases.map(c => [c.name, c] as const))("%s", (_name, c) => {
    const result = validateReviewSubmission(c.body, fixture.slide_size, s => slugs.has(s))
    expect(result.ok).toBe(c.valid)
    if (!result.ok) expect(result.error).toBeTruthy()
  })

  it("trims text and turns an empty note into null", () => {
    const result = validateReviewSubmission(
      { note: "  \n", comments: [{ name: "A", slide: "intro", rect: [0, 0, 10, 10], text: "  直して \n" }] },
      fixture.slide_size, s => slugs.has(s),
    )
    expect(result).toEqual({ ok: true, value: { note: null, comments: [{ name: "A", slide: "intro", rect: [0, 0, 10, 10], text: "直して" }] } })
  })

  it("never asks about a slug that fails the slug grammar", () => {
    const seen: string[] = []
    validateReviewSubmission({ comments: [{ name: "A", slide: "../x", rect: [0, 0, 10, 10], text: "x" }] },
      fixture.slide_size, s => { seen.push(s); return true })
    expect(seen).toEqual([])
  })
})

describe("extractRefs", () => {
  it("keeps known names other than self, ordered and deduped", () => {
    expect(extractRefs("@B と @Bと同じ @Z", ["A", "B"], "A")).toEqual(["B"])
    expect(extractRefs("@C then @B, also @A", ["A", "B", "C"], "A")).toEqual(["C", "B"])
    expect(extractRefs("@BC1 and @Bx", ["B", "BC"], "A")).toEqual([])
  })
})

describe("ids", () => {
  it("formats the id and timestamp in UTC", () => {
    const now = new Date("2026-11-01T19:20:00+09:00")
    const id = newReviewId(now)
    expect(id.startsWith("20261101-102000-")).toBe(true)
    expect(isReviewId(id)).toBe(true)
    expect(createdAtIso(now)).toBe("2026-11-01T10:20:00Z")
  })

  it.each(["../x", "20261101-102000-A1B2", "20261101-102000-a1b2\n", "", null])("rejects %j", v => {
    expect(isReviewId(v)).toBe(false)
  })
})

describe("buildReviewFile", () => {
  it("computes refs and opens every comment", () => {
    const file = buildReviewFile("20261101-102000-a1b2", "2026-11-01T10:20:00Z", [1920, 1080], {
      note: "全体的に",
      comments: [
        { name: "A", slide: "sales", rect: [1248, 238, 576, 400], text: "@B と同じ色で" },
        { name: "B", slide: "intro", rect: [0, 0, 10, 10], text: "見出し @A @A" },
      ],
    })
    expect(file).toEqual({
      version: 1,
      id: "20261101-102000-a1b2",
      created_at: "2026-11-01T10:20:00Z",
      note: "全体的に",
      slide_size: [1920, 1080],
      comments: [
        { name: "A", slide: "sales", rect: [1248, 238, 576, 400], text: "@B と同じ色で", refs: ["B"], status: "open", reply: null },
        { name: "B", slide: "intro", rect: [0, 0, 10, 10], text: "見出し @A @A", refs: ["A"], status: "open", reply: null },
      ],
    })
  })
})

describe("parseReviewFile", () => {
  it("reads a file the agent rewrote and tolerates drift", () => {
    const parsed = parseReviewFile({
      id: "20261101-102000-a1b2",
      note: 5,
      comments: [
        { name: "A", slide: "sales", rect: [1, 2, 3, 4], text: "x", refs: ["B", 3], status: "done", reply: "色を変えました" },
        { name: "B", slide: "intro", rect: [1, 2, 3, 4], text: "y", status: "skipped", reply: { why: 1 } },
        { name: "C", slide: "intro", rect: [1, 2, 3], text: "z" },
        "garbage",
      ],
    })
    expect(parsed).toEqual({
      version: 1,
      id: "20261101-102000-a1b2",
      created_at: "",
      note: null,
      slide_size: [1920, 1080],
      comments: [
        { name: "A", slide: "sales", rect: [1, 2, 3, 4], text: "x", refs: ["B"], status: "done", reply: "色を変えました" },
        { name: "B", slide: "intro", rect: [1, 2, 3, 4], text: "y", refs: [], status: "open", reply: null },
      ],
    })
  })

  it.each([null, [], "x", { comments: [] }, { id: "x" }])("returns null for %j", v => {
    expect(parseReviewFile(v)).toBeNull()
  })
})
