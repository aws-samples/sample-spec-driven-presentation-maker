// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * `[review:<id>]` chat marker: a user message carrying it is a review request, and the
 * orchestrator reads `reviews/<id>.json`. Same convention as `[slide-preview:…]` / `[Attached:…]`.
 */

export const REVIEW_MARKER_RE = /\[review:(\d{8}-\d{6}-[0-9a-f]{4})\]/g

export function buildReviewMarker(id: string): string {
  return `[review:${id}]`
}

/** Review ids in `text`, in order, once each. */
export function parseReviewMarkers(text: string): string[] {
  const ids: string[] = []
  for (const m of text.matchAll(REVIEW_MARKER_RE)) {
    if (!ids.includes(m[1])) ids.push(m[1])
  }
  return ids
}

/** `text` without review markers, trimmed. */
export function stripReviewMarkers(text: string): string {
  return text.replace(REVIEW_MARKER_RE, "").trim()
}
