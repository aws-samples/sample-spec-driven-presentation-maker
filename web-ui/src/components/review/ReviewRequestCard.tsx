// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewRequestCard — a sent 修正依頼 in the chat, drawn in place of the user's message
 * (ChatMessage sizes it: right-aligned, 94% of the chat width).
 *
 * Reads the review file (`reviews/<id>.json`) through the review state: header with the
 * comment count and progress (`done / total`, or 完了), the note, and one row per comment
 * with its status and the agent's reply. A click on an open comment jumps to its frame.
 * Without a review state (or for another deck's chat) only the note is shown.
 * When the chat message carrying the request did not reach the agent, a Retry row sends it again.
 */

"use client"

import { useEffect } from "react"
import type { KeyboardEvent, ReactNode } from "react"
import { Check, Loader2 } from "lucide-react"
import { useTranslations } from "next-intl"
import { sentFrameKey, useReview } from "@/components/review/ReviewProvider"
import { MentionText } from "@/components/review/MentionText"
import type { ReviewComment } from "@/lib/review/schema"

interface ReviewRequestCardProps {
  reviewId: string
  /** The message text without markers (the note for the whole deck). */
  note: string
  /** Deck of the chat this message belongs to; defaults to the open deck. */
  deckId?: string
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="w-full overflow-hidden rounded-xl border border-border bg-background-raised" data-review-request-card>
      {children}
    </div>
  )
}

export function ReviewRequestCard({ reviewId, note, deckId }: ReviewRequestCardProps) {
  const t = useTranslations("review")
  const review = useReview()
  const forDeck = deckId ?? review?.deckId ?? null
  const live = !!review && !!forDeck && forDeck === review.deckId
  const track = review?.track
  const loaded = review?.requests

  // Re-run when the request map changes: the provider loads the deck after its children's
  // first effects, and drops loaded requests on deck change. track() skips known ids.
  useEffect(() => {
    if (live && track && forDeck) track(forDeck, [reviewId])
  }, [live, track, forDeck, reviewId, loaded])

  const header = (extra?: ReactNode) => (
    <div className="flex items-center gap-2 px-3 pt-2.5">
      <span className="h-[7px] w-[7px] flex-none rounded-full bg-human" aria-hidden />
      <span className="text-sm font-semibold">{t("draftTitle")}</span>
      {extra}
    </div>
  )

  if (!review || !live) {
    return (
      <Shell>
        {header()}
        {note && <p className="whitespace-pre-wrap break-words px-3 pb-2.5 pt-2 text-sm leading-relaxed text-foreground-secondary">{note}</p>}
        {!note && <div className="pb-2.5" />}
      </Shell>
    )
  }

  const entry = review.requests.get(reviewId)

  if (entry === undefined || entry === "loading") {
    return (
      <Shell>
        <div className="space-y-2 p-3 animate-pulse" role="status" aria-label={t("loading")}>
          <div className="h-4 w-2/5 rounded bg-foreground/[0.06]" />
          <div className="h-4 w-4/5 rounded bg-foreground/[0.04]" />
          <div className="h-4 w-3/5 rounded bg-foreground/[0.04]" />
        </div>
      </Shell>
    )
  }

  if (entry === "error") {
    return (
      <Shell>
        {header()}
        {note && <p className="whitespace-pre-wrap break-words px-3 pt-2 text-sm leading-relaxed text-foreground-secondary">{note}</p>}
        <p className="px-3 pb-2.5 pt-2 text-xs text-foreground-muted">{t("unreadable")}</p>
      </Shell>
    )
  }

  const comments = entry.comments
  const names = new Set(comments.map(c => c.name))
  const done = comments.filter(c => c.status === "done").length
  const working = review.statusOf(reviewId) === "working"
  const openKeys = new Set(review.openSent.map(f => f.key))
  const exists = (n: string) => names.has(n)
  const keyFor = (n: string) => sentFrameKey(reviewId, n)
  const slideLabel = (slug: string) => {
    const i = review.slugs.indexOf(slug)
    return i >= 0 ? t("slide", { n: i + 1 }) : slug
  }

  const row = (c: ReviewComment) => {
    const key = keyFor(c.name)
    const isDone = c.status === "done"
    const clickable = review.enabled && !isDone && openKeys.has(key)
    const focus = () => review.focusFrame(key)
    const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "Enter" && e.key !== " ") return
      e.preventDefault()
      focus()
    }
    return (
      <div
        key={c.name}
        data-review-comment={c.name}
        data-status={c.status}
        {...(clickable ? { role: "button", tabIndex: 0, onClick: focus, onKeyDown } : {})}
        className={`flex items-start gap-2.5 rounded-lg p-2 ${clickable ? "cursor-pointer hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-human/45" : ""}`}
      >
        <span className={`inline-flex h-5 flex-none items-center gap-[3px] rounded-[5px] px-[7px] text-xs font-bold text-human-ink ${isDone ? "bg-agent-content" : "bg-human"}`}>
          {isDone && <Check className="h-[11px] w-[11px]" aria-hidden />}
          {!isDone && working && <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden />}
          {c.name}
        </span>
        <div className="min-w-0 flex-1">
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            <MentionText text={c.text} exists={exists} keyFor={keyFor} />
          </div>
          <div className="mt-px text-xs text-foreground-muted">
            {slideLabel(c.slide)}
            <span className="sr-only"> · {t(isDone ? "status.done" : working ? "status.working" : "status.sent")}</span>
          </div>
          {c.reply && (
            <div className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-normal text-agent-content" data-review-reply>
              <MentionText text={c.reply} exists={exists} keyFor={keyFor} />
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <Shell>
      {header(
        <>
          <span className="flex-1 text-xs text-foreground-muted">{t("draftCount", { count: comments.length })}</span>
          <span className="text-xs tabular-nums text-foreground-secondary" data-review-progress>
            {done === comments.length ? t("complete") : t("progress", { done, total: comments.length })}
          </span>
        </>,
      )}
      {note && (
        <p className="whitespace-pre-wrap break-words px-3 pt-2 text-sm leading-relaxed text-foreground-secondary">
          <MentionText text={note} exists={exists} keyFor={keyFor} />
        </p>
      )}
      <div className="px-1 py-1.5">{comments.map(row)}</div>
      {review.failed.has(reviewId) && !review.agentBusy && (
        <div className="flex items-center gap-2 border-t border-border px-3 py-2" data-review-failed>
          <span className="flex-1 text-xs text-foreground-secondary">{t("sendFailed")}</span>
          <button
            type="button"
            onClick={() => review.retry(reviewId)}
            className="inline-flex h-7 items-center rounded-md border border-border-hover px-2.5 text-xs text-foreground transition-colors hover:bg-background-hover"
          >
            {t("retry")}
          </button>
        </div>
      )}
    </Shell>
  )
}
