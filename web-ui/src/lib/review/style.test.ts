// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { REVIEW_MARKER_RE, parseReviewMessage } from "./marker"
import { buildStyleReviewMessage, createStyleReview, styleSlideKeys, styleSlideTitle } from "./style"
import type { ReviewSubmission } from "./schema"

const SLIDES = [
  `<div class="slide cover"><div class="el cover-title" style="left:96px; top:300px">Agent<br>spectrum</div></div>`,
  `<div class="slide body"><div class="el" style="left:0; top:0"><span class="t-title">Quarterly   results</span></div><div class="el">body</div></div>`,
  `<div class="slide closing"><div class="el deco"></div><div class="el">Thank you</div></div>`,
  `<div class="slide blank"><div class="el deco"></div></div>`,
]

const json = (message: string) => {
  const start = message.indexOf("```json\n") + "```json\n".length
  return JSON.parse(message.slice(start, message.indexOf("\n```", start)))
}

describe("styleSlideKeys", () => {
  it("numbers the slides from 1", () => {
    expect(styleSlideKeys(3)).toEqual(["1", "2", "3"])
    expect(styleSlideKeys(0)).toEqual([])
  })
})

describe("styleSlideTitle", () => {
  it("reads a slide-title element", () => {
    expect(styleSlideTitle(`<div class="slide"><div class="el slide-title">Agenda</div><div class="el">x</div></div>`)).toBe("Agenda")
  })

  it("reads a t-title inside a span and collapses whitespace", () => {
    expect(styleSlideTitle(SLIDES[1])).toBe("Quarterly results")
  })

  it("reads <br> in a cover-title as a space", () => {
    expect(styleSlideTitle(SLIDES[0])).toBe("Agent spectrum")
  })

  it("falls back to the first .el with text", () => {
    expect(styleSlideTitle(SLIDES[2])).toBe("Thank you")
  })

  it("is null when the slide has no text", () => {
    expect(styleSlideTitle(SLIDES[3])).toBeNull()
    expect(styleSlideTitle("")).toBeNull()
  })

  it("caps the title at 120 characters", () => {
    const title = styleSlideTitle(`<div class="slide"><div class="el slide-title">${"x".repeat(200)}</div></div>`)!
    expect([...title]).toHaveLength(120)
    expect(title.endsWith("…")).toBe(true)
  })
})

const SUBMISSION: ReviewSubmission = {
  note: "overall",
  comments: [
    { name: "A", slide: "1", rect: [10, 20, 300, 200], text: "bigger" },
    { name: "B", slide: "4", rect: [0, 0, 1920, 1080], text: "same colour as @A" },
    { name: "C", slide: "1", rect: [5, 5, 50, 50], text: "" },
  ],
}

describe("buildStyleReviewMessage", () => {
  const message = buildStyleReviewMessage("20261112-213600-c0de", SUBMISSION, s => styleSlideTitle(SLIDES[Number(s) - 1]))

  it("starts with the review marker and mentions no review file", () => {
    expect(message.startsWith("[review:20261112-213600-c0de]\n")).toBe(true)
    expect([...message.matchAll(REVIEW_MARKER_RE)].map(m => m[1])).toEqual(["20261112-213600-c0de"])
    expect(message).not.toContain("reviews/")
    expect(message).toContain("3 comment(s) on 2 slide(s)")
  })

  it("reads back as the same request", () => {
    expect(parseReviewMessage(message)).toEqual({
      id: "20261112-213600-c0de",
      note: "overall",
      comments: [
        { name: "A", slide: "1", rect: [10, 20, 300, 200], text: "bigger" },
        { name: "C", slide: "1", rect: [5, 5, 50, 50], text: "" },
        { name: "B", slide: "4", rect: [0, 0, 1920, 1080], text: "same colour as @A" },
      ],
    })
  })

  it("carries each slide's title, null for a slide without one", () => {
    expect(json(message).slides.map((s: { slide: string; title: string | null }) => [s.slide, s.title])).toEqual([
      ["1", "Agent spectrum"],
      ["4", null],
    ])
  })
})

describe("createStyleReview", () => {
  it("builds a message with a fresh id", () => {
    const { id, message } = createStyleReview(SUBMISSION, SLIDES, new Date(Date.UTC(2026, 10, 12, 21, 36, 0)))
    expect(id).toMatch(/^20261112-213600-[0-9a-f]{4}$/)
    expect(message.startsWith(`[review:${id}]`)).toBe(true)
    expect(json(message).slides[0].title).toBe("Agent spectrum")
  })

  it("rejects a slide that does not exist", () => {
    const submission: ReviewSubmission = { note: null, comments: [{ name: "A", slide: "5", rect: [0, 0, 10, 10], text: "x" }] }
    expect(() => createStyleReview(submission, SLIDES)).toThrow("comments[0].slide does not exist")
  })

  it("rejects frames without any text or note", () => {
    const submission: ReviewSubmission = { note: null, comments: [{ name: "A", slide: "1", rect: [0, 0, 10, 10], text: "" }] }
    expect(() => createStyleReview(submission, SLIDES)).toThrow("a comment text or the note must be non-empty")
  })
})
