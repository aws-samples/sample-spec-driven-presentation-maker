// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Unsent comment frames, kept per deck in localStorage (`sdpm-review-drafts:<deckId>`,
 * `{v: 1, seq, frames}`, rects in slide px). A stored value of the wrong shape is dropped;
 * storage errors (quota, private mode) are swallowed so drawing never fails.
 */

import type { Rect } from "@/lib/review/geometry"
import { NAME_RE } from "@/lib/review/schema"
import { nextSeq } from "@/lib/review/naming"

export interface DraftFrame {
  name: string
  slide: string
  rect: Rect
  text: string
}

export interface DraftState {
  /** Next sequence number for `frameName`; only grows, so deleted names are not reused. */
  seq: number
  frames: DraftFrame[]
}

const VERSION = 1
export const EMPTY_DRAFTS: DraftState = { seq: 0, frames: [] }

export function draftsKey(deckId: string): string {
  return `sdpm-review-drafts:${deckId}`
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage
  } catch {
    return null
  }
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v)

function parseFrame(v: unknown): DraftFrame | null {
  if (!isRecord(v)) return null
  const { name, slide, rect, text } = v
  if (typeof name !== "string" || !NAME_RE.test(name) || typeof slide !== "string" || typeof text !== "string") return null
  if (!Array.isArray(rect) || rect.length !== 4 || !rect.every(n => typeof n === "number" && Number.isFinite(n))) return null
  return { name, slide, rect: [rect[0], rect[1], rect[2], rect[3]], text }
}

/** Drafts stored for `deckId`; empty when nothing (or something malformed) is stored. */
export function loadDrafts(deckId: string): DraftState {
  const raw = (() => {
    try { return storage()?.getItem(draftsKey(deckId)) ?? null } catch { return null }
  })()
  if (!raw) return { ...EMPTY_DRAFTS, frames: [] }
  let data: unknown
  try { data = JSON.parse(raw) } catch { return { ...EMPTY_DRAFTS, frames: [] } }
  if (!isRecord(data) || data.v !== VERSION || !Array.isArray(data.frames)) return { ...EMPTY_DRAFTS, frames: [] }
  const frames: DraftFrame[] = []
  for (const f of data.frames) {
    const frame = parseFrame(f)
    if (!frame) return { ...EMPTY_DRAFTS, frames: [] }
    // A frame always carries a comment; an empty one was still being written when the page closed.
    if (frame.text.trim() && !frames.some(x => x.name === frame.name)) frames.push(frame)
  }
  const stored = typeof data.seq === "number" && Number.isInteger(data.seq) && data.seq >= 0 ? data.seq : 0
  return { seq: Math.max(stored, nextSeq(frames.map(f => f.name))), frames }
}

/** Store drafts for `deckId`. Never throws. */
export function saveDrafts(deckId: string, state: DraftState): void {
  try {
    storage()?.setItem(draftsKey(deckId), JSON.stringify({ v: VERSION, seq: state.seq, frames: state.frames }))
  } catch {
    /* quota exceeded or storage unavailable: drafts live in memory only */
  }
}
