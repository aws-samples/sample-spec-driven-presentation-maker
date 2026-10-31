// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Review request files (`reviews/<id>.json`) — Web UI mirror of `shared/review.py`.
 *
 * The Local API route validates and builds the file with these functions; the UI uses the
 * types and `parseReviewFile` to read files the agent rewrote. Both sides run the cases in
 * `tests/fixtures/review_submissions.json`, and `tests/test_review_contract.py` checks the
 * limits below against the Python constants.
 */

export const REVIEW_VERSION = 1
export const MAX_COMMENTS = 100
export const MAX_TEXT_CHARS = 2000
export const MAX_NOTE_CHARS = 4000
export const MAX_BODY_BYTES = 512 * 1024
export const DEFAULT_SLIDE_SIZE: [number, number] = [1920, 1080]

export const REVIEW_ID_RE = /^\d{8}-\d{6}-[0-9a-f]{4}$/
export const NAME_RE = /^[A-Z]{1,3}$/
export const SLUG_RE = /^[a-z0-9][a-z0-9_-]*$/
/** `@X` mentions. No `\b`, so `@Bと` matches the same way as in Python. */
export const MENTION_RE = /@([A-Z]{1,3})(?![A-Za-z0-9])/g

export type ReviewRect = [number, number, number, number]
export type ReviewStatus = "open" | "done"

export interface ReviewComment {
  name: string
  slide: string
  /** `[x, y, w, h]` in slide px. */
  rect: ReviewRect
  text: string
  refs: string[]
  status: ReviewStatus
  reply: string | null
}

export interface ReviewRequest {
  version: number
  id: string
  created_at: string
  note: string | null
  slide_size: [number, number]
  comments: ReviewComment[]
}

/** What the client sends; the server adds id, timestamp, slide size, refs and status. */
export interface ReviewSubmission {
  note: string | null
  comments: { name: string; slide: string; rect: ReviewRect; text: string }[]
}

export type ValidationResult = { ok: true; value: ReviewSubmission } | { ok: false; error: string }

/** Length in code points, as Python's `len()` counts it. */
function charCount(s: string): number {
  return [...s].length
}

export function isReviewId(value: unknown): value is string {
  return typeof value === "string" && REVIEW_ID_RE.test(value)
}

/** Review id for a submission at `now`: UTC `YYYYMMDD-HHMMSS-` plus 4 random hex digits. */
export function newReviewId(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}`
    + `-${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}`
  const bytes = crypto.getRandomValues(new Uint8Array(2))
  return `${stamp}-${Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("")}`
}

/** `created_at` value for a submission at `now` (UTC, seconds, `Z` suffix). */
export function createdAtIso(now: Date): string {
  return now.toISOString().replace(/\.\d{3}Z$/, "Z")
}

/** Names mentioned as `@X` that belong to the same request, in order, once each, never `selfName`. */
export function extractRefs(text: string, names: Iterable<string>, selfName: string): string[] {
  const known = new Set(names)
  const refs: string[] = []
  for (const m of text.matchAll(MENTION_RE)) {
    const name = m[1]
    if (known.has(name) && name !== selfName && !refs.includes(name)) refs.push(name)
  }
  return refs
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
 * Validate a review submission (same rules and order as `validate_review_submission` in Python).
 * `slugExists` is only called with slugs that passed `SLUG_RE`.
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
    const trimmed = body.note.trim()
    if (charCount(trimmed) > MAX_NOTE_CHARS) return fail(`note exceeds ${MAX_NOTE_CHARS} characters`)
    note = trimmed || null
  }

  const comments = body.comments
  if (!Array.isArray(comments)) return fail("comments must be a list")
  if (comments.length < 1 || comments.length > MAX_COMMENTS) return fail(`comments must hold 1-${MAX_COMMENTS} items`)

  const out: ReviewSubmission["comments"] = []
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
    const text = c.text.trim()
    const len = charCount(text)
    if (len < 1 || len > MAX_TEXT_CHARS) return fail(`${where}.text must be 1-${MAX_TEXT_CHARS} characters`)
    if (seen.has(c.name)) return fail(`${where}.name is duplicated`)
    seen.add(c.name)
    out.push({ name: c.name, slide: c.slide, rect: [...(c.rect as number[])] as ReviewRect, text })
  }
  return { ok: true, value: { note, comments: out } }
}

/** The review file for a validated submission: refs computed, every comment `open`. */
export function buildReviewFile(
  reviewId: string, createdAt: string, slideSize: [number, number], submission: ReviewSubmission,
): ReviewRequest {
  const names = submission.comments.map(c => c.name)
  return {
    version: REVIEW_VERSION,
    id: reviewId,
    created_at: createdAt,
    note: submission.note,
    slide_size: [slideSize[0], slideSize[1]],
    comments: submission.comments.map(c => ({
      name: c.name,
      slide: c.slide,
      rect: [...c.rect] as ReviewRect,
      text: c.text,
      refs: extractRefs(c.text, names, c.name),
      status: "open",
      reply: null,
    })),
  }
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v)

/**
 * Tolerant reader for a review file (the orchestrator rewrites it): unknown status → "open",
 * non-string reply → null, malformed comments dropped. Null when `id` or `comments` is missing.
 */
export function parseReviewFile(json: unknown): ReviewRequest | null {
  if (!isRecord(json) || typeof json.id !== "string" || !Array.isArray(json.comments)) return null
  const size = json.slide_size
  const slideSize: [number, number] = Array.isArray(size) && size.length === 2 && size.every(isFiniteNumber)
    ? [size[0], size[1]] : [...DEFAULT_SLIDE_SIZE]
  const comments: ReviewComment[] = []
  for (const c of json.comments) {
    if (!isRecord(c) || typeof c.name !== "string" || typeof c.slide !== "string" || typeof c.text !== "string") continue
    if (!Array.isArray(c.rect) || c.rect.length !== 4 || !c.rect.every(isFiniteNumber)) continue
    comments.push({
      name: c.name,
      slide: c.slide,
      rect: [...c.rect] as ReviewRect,
      text: c.text,
      refs: Array.isArray(c.refs) ? c.refs.filter((r): r is string => typeof r === "string") : [],
      status: c.status === "done" ? "done" : "open",
      reply: typeof c.reply === "string" ? c.reply : null,
    })
  }
  return {
    version: isFiniteNumber(json.version) ? json.version : REVIEW_VERSION,
    id: json.id,
    created_at: typeof json.created_at === "string" ? json.created_at : "",
    note: typeof json.note === "string" ? json.note : null,
    slide_size: slideSize,
    comments,
  }
}
