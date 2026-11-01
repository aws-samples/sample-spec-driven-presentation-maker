// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewRequestCard — a sent 修正依頼 in the chat, drawn in place of the user's message
 * (ChatMessage sizes it: right-aligned, 94% of the chat width).
 *
 * Built from the message itself (`parseReviewMessage`), so it restores from chat history:
 * header with the frame count, the note, one row per frame (a frame without a comment shows a
 * muted 「コメントなし」). It shows no progress: the agent's reply in the chat tells the result.
 */

"use client"

import { useTranslations } from "next-intl"
import { useReview } from "@/components/review/ReviewProvider"
import { MentionText } from "@/components/review/MentionText"
import type { SentComment, SentReview } from "@/lib/review/marker"

interface ReviewRequestCardProps {
  request: SentReview
  /** Deck of the chat this message belongs to; defaults to the open deck. */
  deckId?: string
}

export function ReviewRequestCard({ request, deckId }: ReviewRequestCardProps) {
  const t = useTranslations("review")
  const review = useReview()
  const forDeck = deckId ?? review?.deckId ?? null
  // The open deck's slide numbers.
  const live = review && forDeck && forDeck === review.deckId ? review : null
  const { note, comments } = request

  const names = new Set(comments.map(c => c.name))
  const exists = (n: string) => names.has(n)
  const slideLabel = (slug: string) => {
    const i = live ? live.slugs.indexOf(slug) : -1
    return i >= 0 ? t("slide", { n: i + 1 }) : slug
  }

  const row = (c: SentComment) => (
    <div key={c.name} data-review-comment={c.name} className="flex items-start gap-2.5 rounded-lg p-2">
      <span className="inline-flex h-5 flex-none items-center rounded-[5px] bg-human px-[7px] text-xs font-bold text-human-ink">
        {c.name}
      </span>
      <div className="min-w-0 flex-1">
        {c.text ? (
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            <MentionText text={c.text} exists={exists} highlight={false} />
          </div>
        ) : (
          <div className="text-sm leading-relaxed text-foreground-muted">{t("noComment")}</div>
        )}
        <div className="mt-px text-xs text-foreground-muted">{slideLabel(c.slide)}</div>
      </div>
    </div>
  )

  return (
    <div className="w-full overflow-hidden rounded-xl border border-border bg-background-raised" data-review-request-card>
      <div className="flex items-center gap-2 px-3 pt-2.5">
        <span className="h-[7px] w-[7px] flex-none rounded-full bg-human" aria-hidden />
        <span className="text-sm font-semibold">{t("draftTitle")}</span>
        <span className="flex-1 text-xs text-foreground-muted">{t("draftCount", { count: comments.length })}</span>
      </div>
      {note && (
        <p className="whitespace-pre-wrap break-words px-3 pt-2 text-sm leading-relaxed text-foreground-secondary">
          <MentionText text={note} exists={exists} highlight={false} />
        </p>
      )}
      <div className="px-1 py-1.5">{comments.map(row)}</div>
    </div>
  )
}
