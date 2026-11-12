// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Change requests from the comment tool on the style preview.
 *
 * Styles have no deck storage, so the request is only a chat message, built here in the
 * browser: the same `[review:<id>]` marker and ```json block as a deck request (so
 * `parseReviewMessage` turns it into the chat card), with a style-specific text and each
 * slide's title. A style slide is keyed by its 1-based position among the style's `.slide`
 * elements ("1", "2", …), the order of `splitStyleSlides`. How the agent handles the request
 * is in `sdpm/references/workflows/style.md`.
 */

import {
  newReviewId, reviewPayload, validateReviewSubmission,
  type ReviewRect, type ReviewSubmission,
} from "./schema"

/** Native size of a style slide. */
export const STYLE_SLIDE_SIZE: [number, number] = [1920, 1080]

const TITLE_MAX_CHARS = 120
const TITLE_CLASS_RE = /(^|-)title$/

/** Keys of a style's slides: `["1", …, String(count)]`. */
export function styleSlideKeys(count: number): string[] {
  return Array.from({ length: Math.max(0, count) }, (_, i) => String(i + 1))
}

const textOf = (el: Element) => (el.textContent ?? "").replace(/\s+/g, " ").trim()

/**
 * The title text of one style slide (its HTML fragment), or null: the first element with a
 * class token ending in `title` (`slide-title`, `cover-title`, …), else the first `.el` with
 * text. Whitespace collapses, `<br>` reads as a space, and the result is capped at 120 characters.
 */
export function styleSlideTitle(slideHtml: string): string | null {
  if (!slideHtml || typeof DOMParser === "undefined") return null
  const doc = new DOMParser().parseFromString(`<body>${slideHtml}</body>`, "text/html")
  for (const br of doc.body.querySelectorAll("br")) br.replaceWith(" ")
  const all = [...doc.body.querySelectorAll("[class]")]
  const titled = all.find(el => [...el.classList].some(c => TITLE_CLASS_RE.test(c)))
  let text = titled ? textOf(titled) : ""
  if (!text) {
    const el = [...doc.body.querySelectorAll(".el")].find(e => textOf(e))
    text = el ? textOf(el) : ""
  }
  if (!text) return null
  const chars = [...text]
  return chars.length > TITLE_MAX_CHARS ? `${chars.slice(0, TITLE_MAX_CHARS - 1).join("")}…` : text
}

interface StylePayloadSlide {
  slide: string
  title: string | null
  comments: { name: string; rect: ReviewRect; text: string }[]
}

/** The JSON block, one line per comment (the layout of `formatReviewPayload`, plus `title`). */
function formatStylePayload(note: string | null, slides: StylePayloadSlide[]): string {
  const lines = [`{"note":${JSON.stringify(note)},"slides":[`]
  slides.forEach((s, i) => {
    lines.push(`  {"slide":${JSON.stringify(s.slide)},"title":${JSON.stringify(s.title)},"comments":[`)
    s.comments.forEach((c, j) => lines.push(`    ${JSON.stringify(c)}${j < s.comments.length - 1 ? "," : ""}`))
    lines.push(`  ]}${i < slides.length - 1 ? "," : ""}`)
  })
  lines.push("]}")
  return lines.join("\n")
}

/** The chat message for a validated style submission. */
export function buildStyleReviewMessage(
  id: string, submission: ReviewSubmission, titleOf: (slide: string) => string | null,
): string {
  const payload = reviewPayload(submission)
  const slides = payload.slides.map(s => ({ slide: s.slide, title: titleOf(s.slide), comments: s.comments }))
  return [
    `[review:${id}]`,
    `Change request from the style preview in the Web UI: the user drew ${submission.comments.length} comment(s) on ${slides.length} slide(s) of this style. They are repeated below as JSON: \`note\` is the user's message for the whole request (null when empty), and \`slides\` lists each commented slide by \`slide\` (its number: the position of its \`.slide\` element in the style file, counting from 1) and \`title\` (the slide's title text, null when it has none), with its comments, each with \`name\`, \`rect\` ([x, y, width, height] in px of the 1920×1080 slide, the coordinates of the \`.el\` inline styles) and \`text\` (empty for a frame the other texts point to). \`@X\` in a text refers to comment X.`,
    "",
    "```json",
    formatStylePayload(payload.note, slides),
    "```",
  ].join("\n")
}

/**
 * Validate `submission` against the style's current slides (their HTML fragments, in order)
 * and build its chat message. Throws with the validation error.
 */
export function createStyleReview(
  submission: ReviewSubmission, slides: string[], now = new Date(),
): { id: string; message: string } {
  const keys = new Set(styleSlideKeys(slides.length))
  const result = validateReviewSubmission(submission, STYLE_SLIDE_SIZE, s => keys.has(s))
  if (!result.ok) throw new Error(result.error)
  const id = newReviewId(now)
  const message = buildStyleReviewMessage(id, result.value, s => styleSlideTitle(slides[Number(s) - 1] ?? ""))
  return { id, message }
}
