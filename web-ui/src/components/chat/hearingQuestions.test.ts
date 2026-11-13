// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The hearing input reader keeps the current shape, still reads older chat history
 * (inference, string options, question-level recommended, q4) and tolerates partial
 * streaming input; the answer formatter keeps the `question: answer` lines.
 */

import { describe, expect, it } from "vitest"
import {
  EMPTY_ANSWER,
  fallbackHeader,
  formatAnswers,
  normalizeHearingInput,
  type HearingAnswer,
} from "./hearingQuestions"

describe("normalizeHearingInput", () => {
  it("passes the current shape through", () => {
    const qs = normalizeHearingInput({
      q0: {
        header: "聞き手",
        type: "single_select",
        text: "誰に向けた発表ですか?",
        options: [
          { label: "経営層", description: "要点と数字を先に出す", recommended: true },
          { label: "開発チーム", description: "実装の詳細まで" },
        ],
      },
      q1: { header: "補足", type: "free_text", text: "必ず触れたい点", placeholder: "例: コスト" },
    })
    expect(qs).toEqual([
      {
        id: "q0",
        type: "single_select",
        header: "聞き手",
        text: "誰に向けた発表ですか?",
        options: [
          { label: "経営層", description: "要点と数字を先に出す", recommended: true },
          { label: "開発チーム", description: "実装の詳細まで" },
        ],
      },
      { id: "q1", type: "free_text", header: "補足", text: "必ず触れたい点", options: [], placeholder: "例: コスト" },
    ])
  })

  it("reads older history: inference ignored, string options, legacy recommended, q4", () => {
    const input = {
      inference: "My hypothesis",
      q0: { type: "single_select", text: "One", options: ["A", "B"], recommended: "B" },
      q1: { type: "multi_select", text: "Many", options: ["X", "Y", "Z"], recommended: ["X", "Z"] },
      q2: { type: "free_text", text: "Free" },
      q3: { type: "single_select", text: "Three", options: ["P", "Q"] },
      q4: { type: "single_select", text: "Five", options: ["M", "N"] },
    }
    const qs = normalizeHearingInput(input)
    expect(qs.map((q) => q.id)).toEqual(["q0", "q1", "q2", "q3", "q4"])
    expect(qs[0].options).toEqual([{ label: "A" }, { label: "B", recommended: true }])
    expect(qs[1].options.filter((o) => o.recommended).map((o) => o.label)).toEqual(["X", "Z"])
    expect(qs.every((q) => q.header === undefined)).toBe(true)
    expect(JSON.stringify(qs)).not.toContain("My hypothesis")
  })

  it("reads a questions array", () => {
    const qs = normalizeHearingInput({ questions: [{ id: "a", text: "T", options: ["1", "2"] }, { text: "U" }] })
    expect(qs.map((q) => [q.id, q.type])).toEqual([["a", "single_select"], ["q1", "free_text"]])
  })

  it("tolerates partial streaming input", () => {
    expect(() => normalizeHearingInput({ q0: { type: "single_select" } })).not.toThrow()
    const qs = normalizeHearingInput({ q0: { header: "H", text: "Q", options: [{ label: "A" }, {}, { label: "" }] }, q1: "pending" })
    expect(qs).toHaveLength(1)
    expect(qs[0].options).toEqual([{ label: "A" }])
    expect(normalizeHearingInput({ q0: { type: "single_select" } })[0].text).toBe("")
    expect(normalizeHearingInput(undefined)).toEqual([])
  })
})

describe("fallbackHeader", () => {
  it("shortens long text by characters, Japanese included", () => {
    expect(fallbackHeader("誰に向けた発表ですか？聞き手を教えてください")).toBe("誰に向けた発表ですか？聞…")
    expect(fallbackHeader("Pick one")).toBe("Pick one")
    expect(fallbackHeader("")).toBe("")
  })
})

describe("formatAnswers", () => {
  const qs = normalizeHearingInput({
    q0: { header: "One", type: "single_select", text: "Single", options: [{ label: "A" }, { label: "B" }] },
    q1: { header: "Many", type: "multi_select", text: "Multi", options: [{ label: "X" }, { label: "Y" }, { label: "Z" }] },
    q2: { header: "Free", type: "free_text", text: "Free" },
    q3: { header: "Skip", type: "single_select", text: "Skipped", options: [{ label: "P" }, { label: "Q" }] },
  })
  const a = (patch: Partial<HearingAnswer>): HearingAnswer => ({ ...EMPTY_ANSWER, ...patch })

  it("joins one line per answered question, options in their order, other last", () => {
    const text = formatAnswers(qs, {
      q0: a({ selected: ["B"] }),
      q1: a({ selected: ["Z", "X"], otherOn: true, other: "  my own  " }),
      q2: a({ text: " notes " }),
      q3: a({}),
    })
    expect(text).toBe("Single: B\nMulti: X, Z, my own\nFree: notes")
  })

  it("leaves out other text when other is switched off, and empty answers", () => {
    expect(formatAnswers(qs, { q0: a({ otherOn: false, other: "hidden" }), q1: a({ otherOn: true, other: "   " }) })).toBe("")
    expect(formatAnswers(qs, { q0: a({ otherOn: true, other: "custom" }) })).toBe("Single: custom")
  })
})
