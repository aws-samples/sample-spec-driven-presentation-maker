// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * hearingQuestions — reads the `hearing` tool input into the questions HearingCard shows,
 * and turns the user's answers into the chat message the agent receives.
 *
 * Current input: `q0`…`q3`, each `{header, type, text, options: [{label, description,
 * recommended}], placeholder}`. Older chat history may hold `inference` (ignored), string
 * options, a question-level `recommended` (string or string[]) and `q4`; those still render.
 * The input can be partial while it streams in, so every field is optional here.
 */

export type HearingQuestionType = "single_select" | "multi_select" | "free_text"

export interface HearingOption {
  label: string
  description?: string
  recommended?: boolean
}

export interface HearingQuestion {
  id: string
  type: HearingQuestionType
  header?: string
  text: string
  options: HearingOption[]
  placeholder?: string
}

export interface HearingAnswer {
  /** Selected option labels (select types). */
  selected: string[]
  /** Whether the "Other" choice is on (select types). */
  otherOn: boolean
  /** Text of the "Other" choice. */
  other: string
  /** Free-text answer (free_text). */
  text: string
}

export const EMPTY_ANSWER: HearingAnswer = { selected: [], otherOn: false, other: "", text: "" }

const TYPES: readonly HearingQuestionType[] = ["single_select", "multi_select", "free_text"]
const QUESTION_KEYS = ["q0", "q1", "q2", "q3", "q4"] // q4: older history only

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v)

function normalizeOptions(raw: unknown, legacyRecommended: unknown): HearingOption[] {
  if (!Array.isArray(raw)) return []
  const legacy = new Set(
    typeof legacyRecommended === "string" ? [legacyRecommended]
      : Array.isArray(legacyRecommended) ? legacyRecommended.filter((r): r is string => typeof r === "string")
        : [],
  )
  const options: HearingOption[] = []
  for (const item of raw) {
    let option: HearingOption | null = null
    if (typeof item === "string") option = { label: item }
    else if (isObject(item) && item.label != null) {
      option = { label: String(item.label) }
      if (typeof item.description === "string" && item.description) option.description = item.description
      if (item.recommended === true) option.recommended = true
    }
    if (!option || !option.label.trim()) continue
    if (legacy.has(option.label)) option.recommended = true
    options.push(option)
  }
  return options
}

function normalizeQuestion(raw: Record<string, unknown>, id: string): HearingQuestion {
  const options = normalizeOptions(raw.options, raw.recommended)
  const type = TYPES.includes(raw.type as HearingQuestionType)
    ? (raw.type as HearingQuestionType)
    : options.length > 0 ? "single_select" : "free_text"
  const question: HearingQuestion = { id, type, text: typeof raw.text === "string" ? raw.text : "", options }
  const header = typeof raw.header === "string" ? raw.header.trim() : ""
  if (header) question.header = header
  if (typeof raw.placeholder === "string" && raw.placeholder) question.placeholder = raw.placeholder
  return question
}

/** The questions in a `hearing` tool input, current or older shape, possibly still streaming. */
export function normalizeHearingInput(input: Record<string, unknown> | undefined | null): HearingQuestion[] {
  if (!input) return []
  if (Array.isArray(input.questions)) {
    return input.questions
      .filter(isObject)
      .map((q, i) => normalizeQuestion(q, typeof q.id === "string" && q.id ? q.id : `q${i}`))
  }
  return QUESTION_KEYS.flatMap((key) => (isObject(input[key]) ? [normalizeQuestion(input[key] as Record<string, unknown>, key)] : []))
}

/** A chip label for a question without `header` (older history): the first 12 characters. */
export function fallbackHeader(text: string): string {
  const chars = Array.from(text.trim())
  if (chars.length === 0) return ""
  return chars.length > 12 ? `${chars.slice(0, 12).join("")}…` : chars.join("")
}

/** The answer as it is sent to the agent; "" when the question is unanswered. */
export function answerValue(question: HearingQuestion, answer: HearingAnswer | undefined): string {
  if (!answer) return ""
  if (question.type === "free_text") return answer.text.trim()
  const selected = question.options.filter((o) => answer.selected.includes(o.label)).map((o) => o.label)
  const other = answer.otherOn ? answer.other.trim() : ""
  return [...selected, ...(other ? [other] : [])].join(", ")
}

export function isAnswered(question: HearingQuestion, answer: HearingAnswer | undefined): boolean {
  return answerValue(question, answer) !== ""
}

/** The chat message: one `question: answer` line per answered question. */
export function formatAnswers(questions: HearingQuestion[], answers: Record<string, HearingAnswer>): string {
  return questions
    .map((q) => {
      const value = answerValue(q, answers[q.id])
      return value ? `${q.text}: ${value}` : null
    })
    .filter((line): line is string => line !== null)
    .join("\n")
}
