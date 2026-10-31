// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Reading a change request back from its chat message.
 *
 * The server builds the message from `shared/review_template.json`: it starts with the
 * `[review:<id>]` marker and carries the request as a ```json block (note + comments grouped
 * by slide). The chat card and the sent frames are built from that block, so they restore
 * from chat history in both modes (Cloud history keeps the message sent to the agent, Local
 * `.chat.json` the display text, which is the same message).
 */

import type { ReviewRect } from "./schema"

export const REVIEW_MARKER_RE = /\[review:(\d{8}-\d{6}-[0-9a-f]{4})\]/g

const BLOCK_OPEN = "```json\n"
const BLOCK_CLOSE = "\n```"

export interface SentComment {
  name: string
  slide: string
  rect: ReviewRect
  text: string
}

/** A change request as carried by its chat message. */
export interface SentReview {
  id: string
  note: string | null
  /** In sent order, slide by slide. */
  comments: SentComment[]
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v)
const isRect = (v: unknown): v is ReviewRect =>
  Array.isArray(v) && v.length === 4 && v.every(n => typeof n === "number" && Number.isFinite(n))

function parsePayload(id: string, json: unknown): SentReview | null {
  if (!isRecord(json) || !Array.isArray(json.slides)) return null
  if (json.note !== null && typeof json.note !== "string") return null
  const comments: SentComment[] = []
  for (const s of json.slides) {
    if (!isRecord(s) || typeof s.slide !== "string" || !Array.isArray(s.comments)) return null
    for (const c of s.comments) {
      if (!isRecord(c) || typeof c.name !== "string" || typeof c.text !== "string" || !isRect(c.rect)) return null
      comments.push({ name: c.name, slide: s.slide, rect: [...c.rect] as ReviewRect, text: c.text })
    }
  }
  if (!comments.length) return null
  return { id, note: json.note, comments }
}

/**
 * The change request in a chat message, or null when `text` is not one (or the block is
 * damaged). Cheap for ordinary messages: it only parses after a marker.
 */
export function parseReviewMessage(text: string): SentReview | null {
  for (const m of text.matchAll(REVIEW_MARKER_RE)) {
    const start = text.indexOf(BLOCK_OPEN, (m.index ?? 0) + m[0].length)
    if (start < 0) continue
    const end = text.indexOf(BLOCK_CLOSE, start + BLOCK_OPEN.length)
    if (end < 0) continue
    try {
      const review = parsePayload(m[1], JSON.parse(text.slice(start + BLOCK_OPEN.length, end)))
      if (review) return review
    } catch {
      /* not this block */
    }
  }
  return null
}
