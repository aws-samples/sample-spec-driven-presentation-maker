// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewRequestCard — a sent 修正依頼 in the chat, drawn in place of the user's message
 * (ChatMessage sizes it: right-aligned, 94% of the chat width).
 *
 * Built from the message itself (`parseReviewMessage`), so it restores from chat history:
 * header with the comment count and 対応中 while the agent turn for this message runs, 完了
 * after it; the note; one row per comment. While the request is in progress a click on a
 * comment jumps to its frame. When the chat message did not reach the agent, a Retry row
 * sends it again instead of the status.
 */

"use client"

import type { KeyboardEvent, ReactNode } from "react"
import { Loader2 } from "lucide-react"
import { useTranslations } from "next-intl"
import { sentFrameKey, useReview } from "@/components/review/ReviewProvider"
import { MentionText } from "@/components/review/MentionText"
import type { SentComment, SentReview } from "@/lib/review/marker"

interface ReviewRequestCardProps {
  request: SentReview
  /** The agent turn for this message is running. */
  working: boolean
  /** Deck of the chat this message belongs to; defaults to the open deck. */
  deckId?: string
}

export function ReviewRequestCard({ request, working, deckId }: ReviewRequestCardProps) {
  const t = useTranslations("review")
  const review = useReview()
  const forDeck = deckId ?? review?.deckId ?? null
  // The open deck's state: slide numbers, frames on the canvas, a failed send.
  const live = review && forDeck && forDeck === review.deckId ? review : null
  const { id, note, comments } = request

  const names = new Set(comments.map(c => c.name))
  const exists = (n: string) => names.has(n)
  const keyFor = (n: string) => sentFrameKey(id, n)
  const failed = !!live?.failed.has(id) && !live.agentBusy
  const slideLabel = (slug: string) => {
    const i = live ? live.slugs.indexOf(slug) : -1
    return i >= 0 ? t("slide", { n: i + 1 }) : slug
  }

  const row = (c: SentComment) => {
    const key = keyFor(c.name)
    const clickable = !!live?.enabled && live.lookup(key)?.kind === "sent"
    const focus = () => live?.focusFrame(key)
    const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "Enter" && e.key !== " ") return
      e.preventDefault()
      focus()
    }
    return (
      <div
        key={c.name}
        data-review-comment={c.name}
        {...(clickable ? { role: "button", tabIndex: 0, onClick: focus, onKeyDown } : {})}
        className={`flex items-start gap-2.5 rounded-lg p-2 ${clickable ? "cursor-pointer hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-human/45" : ""}`}
      >
        <span className="inline-flex h-5 flex-none items-center rounded-[5px] bg-human px-[7px] text-xs font-bold text-human-ink">
          {c.name}
        </span>
        <div className="min-w-0 flex-1">
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            <MentionText text={c.text} exists={exists} keyFor={keyFor} />
          </div>
          <div className="mt-px text-xs text-foreground-muted">{slideLabel(c.slide)}</div>
        </div>
      </div>
    )
  }

  let status: ReactNode = null
  if (!failed) {
    status = working ? (
      <span className="flex items-center gap-1 text-xs text-foreground-secondary" data-review-status="working">
        <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden />
        {t("status.working")}
      </span>
    ) : (
      <span className="text-xs text-foreground-secondary" data-review-status="done">{t("complete")}</span>
    )
  }

  return (
    <div className="w-full overflow-hidden rounded-xl border border-border bg-background-raised" data-review-request-card>
      <div className="flex items-center gap-2 px-3 pt-2.5">
        <span className="h-[7px] w-[7px] flex-none rounded-full bg-human" aria-hidden />
        <span className="text-sm font-semibold">{t("draftTitle")}</span>
        <span className="flex-1 text-xs text-foreground-muted">{t("draftCount", { count: comments.length })}</span>
        {status}
      </div>
      {note && (
        <p className="whitespace-pre-wrap break-words px-3 pt-2 text-sm leading-relaxed text-foreground-secondary">
          <MentionText text={note} exists={exists} keyFor={keyFor} />
        </p>
      )}
      <div className="px-1 py-1.5">{comments.map(row)}</div>
      {failed && (
        <div className="flex items-center gap-2 border-t border-border px-3 py-2" data-review-failed>
          <span className="flex-1 text-xs text-foreground-secondary">{t("sendFailed")}</span>
          <button
            type="button"
            onClick={() => live?.retry(id)}
            className="inline-flex h-7 items-center rounded-md border border-border-hover px-2.5 text-xs text-foreground transition-colors hover:bg-background-hover"
          >
            {t("retry")}
          </button>
        </div>
      )}
    </div>
  )
}
