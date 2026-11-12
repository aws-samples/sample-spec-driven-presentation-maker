// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Change requests from the comment tool — Web UI mirror of `shared/review.py`.
 *
 * The Local API route validates the submission, writes `reviews/<id>.json` and returns the
 * chat message with these functions; the texts come from `shared/review_template.json`
 * (loaded by `@/lib/local/reviewTemplate`). Both sides run the cases in
 * `tests/fixtures/review_submissions.json`, and `tests/test_review_contract.py` checks the
 * limits below against the Python constants.
 */

export const MAX_COMMENTS = 100
export const MAX_TEXT_CHARS = 2000
export const MAX_NOTE_CHARS = 4000
export const MAX_BODY_BYTES = 512 * 1024
/**
 * What a note and a comment text are stripped of, and what counts as empty — `WHITESPACE` in
 * Python (its `str.isspace` set plus U+FEFF). `trim()` alone misses U+001C-U+001F and U+0085.
 */
export const WHITESPACE = "\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"

export const NAME_RE = /^[A-Z]{1,3}$/
/** Slide slug of a comment: `SLUG_RE` in sdpm.engine.schema (tests/test_slug_parity.py). */
export const SLUG_RE = /^[a-z0-9][a-z0-9_-]*$/
/** `@X` mentions. No `\b`, so `@Bと` matches. */
export const MENTION_RE = /@([A-Z]{1,3})(?![A-Za-z0-9])/g

export type ReviewRect = [number, number, number, number]

export interface ReviewComment {
  name: string
  slide: string
  /** `[x, y, w, h]` in slide px. */
  rect: ReviewRect
  text: string
}

/** What the client sends; the server adds the id and the slide size. */
export interface ReviewSubmission {
  note: string | null
  comments: ReviewComment[]
}

/** `reviews/<id>.json`: what was sent plus the composers' guide. Nobody rewrites it. */
export interface ReviewFile {
  id: string
  note: string | null
  slide_size: [number, number]
  guide: string
  comments: ReviewComment[]
}

/** The texts in `shared/review_template.json`. */
export interface ReviewTemplate {
  message: string[]
  guide: string
}

/** The message's JSON block: the note and the comments grouped by slide. */
export interface ReviewPayload {
  note: string | null
  slides: { slide: string; comments: { name: string; rect: ReviewRect; text: string }[] }[]
}

export type ValidationResult = { ok: true; value: ReviewSubmission } | { ok: false; error: string }

/** Length in code points, as Python's `len()` counts it. */
function charCount(s: string): number {
  return [...s].length
}

const WHITESPACE_SET = new Set(WHITESPACE)

/** `s` without leading and trailing `WHITESPACE` (Python's `s.strip(WHITESPACE)`). */
export function stripWhitespace(s: string): string {
  let start = 0
  let end = s.length
  while (start < end && WHITESPACE_SET.has(s[start])) start++
  while (end > start && WHITESPACE_SET.has(s[end - 1])) end--
  return s.slice(start, end)
}

/** Review id for a submission at `now`: UTC `YYYYMMDD-HHMMSS-` plus 4 random hex digits. */
export function newReviewId(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}`
    + `-${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}`
  const bytes = crypto.getRandomValues(new Uint8Array(2))
  return `${stamp}-${Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("")}`
}

/** Workspace path of a review file; `reviewId` comes from `newReviewId`. */
export function reviewPath(reviewId: string): string {
  return `reviews/${reviewId}.json`
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v)

function validateRect(rect: unknown, [width, height]: [number, number]): string | null {
  if (!Array.isArray(rect) || rect.length !== 4 || !rect.every(v => typeof v === "number" && Number.isInteger(v))) {
    return "rect must be a list of 4 integers"
  }
  const [x, y, w, h] = rect as number[]
  if (x < 0 || y < 0) return "rect x and y must be >= 0"
  if (w < 1 || h < 1) return "rect width and height must be >= 1"
  if (x + w > width || y + h > height) return "rect must lie inside the slide"
  return null
}

/**
 * Validate a change request (same rules and order as `validate_review_submission` in Python).
 * A comment text may be empty (a frame the other texts point to); at least one text or the
 * note must not be. `slugExists` is only called with slugs that passed `SLUG_RE`.
 */
export function validateReviewSubmission(
  body: unknown, slideSize: [number, number], slugExists: (slug: string) => boolean,
): ValidationResult {
  const fail = (error: string): ValidationResult => ({ ok: false, error })
  if (!isRecord(body)) return fail("body must be an object")

  let note: string | null = null
  if (body.note !== undefined && body.note !== null) {
    if (typeof body.note !== "string") return fail("note must be a string or null")
    if (body.note.includes("\0")) return fail("note must not contain NUL")
    const trimmed = stripWhitespace(body.note)
    if (charCount(trimmed) > MAX_NOTE_CHARS) return fail(`note exceeds ${MAX_NOTE_CHARS} characters`)
    note = trimmed || null
  }

  const comments = body.comments
  if (!Array.isArray(comments)) return fail("comments must be a list")
  if (comments.length < 1 || comments.length > MAX_COMMENTS) return fail(`comments must hold 1-${MAX_COMMENTS} items`)

  const out: ReviewComment[] = []
  const seen = new Set<string>()
  for (const [i, c] of comments.entries()) {
    const where = `comments[${i}]`
    if (!isRecord(c)) return fail(`${where} must be an object`)
    if (typeof c.name !== "string" || !NAME_RE.test(c.name)) return fail(`${where}.name must be 1-3 uppercase letters`)
    if (typeof c.slide !== "string" || !SLUG_RE.test(c.slide)) return fail(`${where}.slide is not a valid slug`)
    if (!slugExists(c.slide)) return fail(`${where}.slide does not exist`)
    const rectError = validateRect(c.rect, slideSize)
    if (rectError) return fail(`${where}.${rectError}`)
    if (typeof c.text !== "string") return fail(`${where}.text must be a string`)
    if (c.text.includes("\0")) return fail(`${where}.text must not contain NUL`)
    const text = stripWhitespace(c.text)
    if (charCount(text) > MAX_TEXT_CHARS) return fail(`${where}.text exceeds ${MAX_TEXT_CHARS} characters`)
    if (seen.has(c.name)) return fail(`${where}.name is duplicated`)
    seen.add(c.name)
    out.push({ name: c.name, slide: c.slide, rect: [...(c.rect as number[])] as ReviewRect, text })
  }
  if (note === null && !out.some(c => c.text)) return fail("a comment text or the note must be non-empty")
  return { ok: true, value: { note, comments: out } }
}

/** The review file for a validated submission: what was sent plus the composers' guide. */
export function buildReviewFile(
  reviewId: string, slideSize: [number, number], submission: ReviewSubmission, template: ReviewTemplate,
): ReviewFile {
  return {
    id: reviewId,
    note: submission.note,
    slide_size: [slideSize[0], slideSize[1]],
    guide: template.guide,
    comments: submission.comments.map(c => ({ name: c.name, slide: c.slide, rect: [...c.rect] as ReviewRect, text: c.text })),
  }
}

/** The message's JSON block: the note and the comments grouped by slide, in sent order. */
export function reviewPayload(submission: ReviewSubmission): ReviewPayload {
  const slides = new Map<string, ReviewPayload["slides"][number]["comments"]>()
  for (const c of submission.comments) {
    const list = slides.get(c.slide) ?? []
    list.push({ name: c.name, rect: [...c.rect] as ReviewRect, text: c.text })
    slides.set(c.slide, list)
  }
  return { note: submission.note, slides: [...slides].map(([slide, comments]) => ({ slide, comments })) }
}

/** The payload as JSON with one line per comment (same text as `format_review_payload` in Python). */
export function formatReviewPayload(payload: ReviewPayload): string {
  const lines = [`{"note":${JSON.stringify(payload.note)},"slides":[`]
  payload.slides.forEach((s, i) => {
    lines.push(`  {"slide":${JSON.stringify(s.slide)},"comments":[`)
    s.comments.forEach((c, j) => lines.push(`    ${JSON.stringify(c)}${j < s.comments.length - 1 ? "," : ""}`))
    lines.push(`  ]}${i < payload.slides.length - 1 ? "," : ""}`)
  })
  lines.push("]}")
  return lines.join("\n")
}

/** The chat message for a validated submission (the template filled in one pass). */
export function buildReviewMessage(reviewId: string, submission: ReviewSubmission, template: ReviewTemplate): string {
  const payload = reviewPayload(submission)
  const values: Record<string, string> = {
    id: reviewId,
    path: reviewPath(reviewId),
    count: String(submission.comments.length),
    slides: String(payload.slides.length),
    payload: formatReviewPayload(payload),
  }
  return template.message.join("\n").replace(/\{(\w+)\}/g, (whole, key: string) => values[key] ?? whole)
}
