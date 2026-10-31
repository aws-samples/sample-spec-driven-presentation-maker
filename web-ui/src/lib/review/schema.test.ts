// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Change request contract — the same fixture as tests/test_review_schema.py, so the Python
 * validator and builders (Cloud) and these (Local) accept the same submissions and produce
 * the same file and message from `shared/review_template.json`.
 */

import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"
import { buildReviewFile, buildReviewMessage, newReviewId, validateReviewSubmission, type ReviewSubmission, type ReviewTemplate } from "./schema"

interface Fixture {
  slide_size: [number, number]
  slugs: string[]
  cases: { name: string; body: unknown; valid: boolean }[]
  message_case: {
    id: string
    slide_size: [number, number]
    normalized: ReviewSubmission
    expected_message: string
    expected_file_without_guide: Record<string, unknown>
  }
}

const repo = path.resolve(__dirname, "../../../..")
const fixture = JSON.parse(fs.readFileSync(path.join(repo, "tests/fixtures/review_submissions.json"), "utf-8")) as Fixture
const template = JSON.parse(fs.readFileSync(path.join(repo, "shared/review_template.json"), "utf-8")) as ReviewTemplate
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

describe("newReviewId", () => {
  it("formats the id in UTC", () => {
    const id = newReviewId(new Date("2026-11-01T19:20:00+09:00"))
    expect(id).toMatch(/^20261101-102000-[0-9a-f]{4}$/)
  })
})

describe("builders", () => {
  const c = fixture.message_case

  it("writes only what was sent plus the guide", () => {
    const file = buildReviewFile(c.id, c.slide_size, c.normalized, template)
    expect(file).toEqual({ ...c.expected_file_without_guide, guide: template.guide })
    expect(Object.keys(file)).toEqual(["id", "note", "slide_size", "guide", "comments"])
  })

  it("builds the same message as the Python server", () => {
    expect(buildReviewMessage(c.id, c.normalized, template)).toBe(c.expected_message)
  })
})
