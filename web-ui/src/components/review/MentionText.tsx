// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * MentionText — comment text with `@X` references drawn in the annotation colour.
 * A reference to a frame that does not exist is muted and struck through. Hovering a
 * reference highlights that frame on the canvas (through the review state, when present).
 */

"use client"

import { Fragment } from "react"
import { MENTION_RE } from "@/lib/review/schema"
import { useReview } from "@/components/review/ReviewProvider"

interface MentionTextProps {
  text: string
  /** Whether `@name` points at an existing frame. */
  exists: (name: string) => boolean
  /** Frame key to highlight for `@name` (drafts: the name; sent: `<requestId>/<name>`). */
  keyFor?: (name: string) => string
}

export function MentionText({ text, exists, keyFor }: MentionTextProps) {
  const review = useReview()
  const parts: React.ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(MENTION_RE)) {
    const start = m.index ?? 0
    if (start > last) parts.push(<Fragment key={`t${last}`}>{text.slice(last, start)}</Fragment>)
    const name = m[1]
    const ok = exists(name)
    const key = keyFor ? keyFor(name) : name
    parts.push(
      <span
        key={`m${start}`}
        data-mention={name}
        className={ok ? "font-semibold text-human-text" : "text-muted-foreground line-through"}
        onMouseEnter={ok && review ? () => review.setHighlight(key) : undefined}
        onMouseLeave={ok && review ? () => review.setHighlight(null) : undefined}
      >
        @{name}
      </span>,
    )
    last = start + m[0].length
  }
  if (last < text.length) parts.push(<Fragment key={`t${last}`}>{text.slice(last)}</Fragment>)
  return <>{parts}</>
}
