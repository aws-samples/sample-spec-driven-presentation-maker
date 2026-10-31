// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewDraftBar — the unsent comments collected above the chat input (the 修正依頼 block).
 *
 * Collapsed: dot + title + count + chevron. Expanded: one row per comment ready to send
 * (tag, text with @ references, slide number, delete on hover); a row click jumps to the
 * frame and opens its card. Renders nothing without a provider or without ready comments.
 */

"use client"

import { useState } from "react"
import type { KeyboardEvent } from "react"
import { ChevronDown, Trash2 } from "lucide-react"
import { useTranslations } from "next-intl"
import { useReview } from "@/components/review/ReviewProvider"
import { MentionText } from "@/components/review/MentionText"

export function ReviewDraftBar() {
  const t = useTranslations("review")
  const review = useReview()
  const [open, setOpen] = useState(false)
  if (!review || !review.enabled) return null
  const drafts = review.readyDrafts
  if (drafts.length === 0) return null
  const names = new Set(review.drafts.map(d => d.name))

  const slideLabel = (slug: string) => {
    const i = review.slugs.indexOf(slug)
    return i >= 0 ? t("slide", { n: i + 1 }) : slug
  }

  return (
    <div className="mx-1.5 mt-1.5 rounded-[9px] bg-human/8 ring-1 ring-inset ring-human/28" data-review-draft-bar>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        title={open ? t("hideComments") : t("showComments")}
        className="flex w-full items-center gap-2 py-1.5 pl-2.5 pr-1.5 text-left"
      >
        <span className="h-[7px] w-[7px] flex-none rounded-full bg-human" aria-hidden />
        <span className="text-sm font-semibold text-human-text">{t("draftTitle")}</span>
        <span className="flex-1 text-xs text-foreground-secondary">{t("draftCount", { count: drafts.length })}</span>
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-md text-foreground-muted hover:bg-foreground/[0.06] hover:text-foreground">
          <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-150 ${open ? "rotate-180" : ""}`} aria-hidden />
        </span>
      </button>
      {open && (
        <div className="max-h-60 overflow-auto border-t border-human/18 px-1 pb-1">
          {drafts.map(d => {
            const focus = () => review.focusFrame(d.name)
            const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
              if (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " ")) return
              e.preventDefault()
              focus()
            }
            return (
              <div
                key={d.name}
                role="button"
                tabIndex={0}
                onClick={focus}
                onKeyDown={onKeyDown}
                onMouseEnter={() => review.setHighlight(d.name)}
                onMouseLeave={() => review.setHighlight(null)}
                className="group/row flex cursor-pointer items-start gap-2.5 rounded-lg p-2 hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-human/45"
                data-review-draft-row={d.name}
              >
                <span className="inline-flex h-5 flex-none items-center rounded-[5px] bg-human px-[7px] text-xs font-bold text-human-ink">{d.name}</span>
                <div className="min-w-0 flex-1">
                  <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                    <MentionText text={d.text} exists={n => names.has(n)} />
                  </div>
                  <div className="mt-px text-xs text-foreground-muted">{slideLabel(d.slide)}</div>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); review.deleteFrame(d.name) }}
                  aria-label={t("deleteLabel")}
                  title={t("deleteLabel")}
                  className="-mr-0.5 -mt-0.5 inline-flex h-6 w-6 flex-none items-center justify-center rounded-md text-foreground-muted opacity-0 hover:bg-foreground/[0.06] hover:text-foreground focus-visible:opacity-100 group-hover/row:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>
            )
          })}
        </div>
      )}
      {review.agentBusy && (
        <p className="px-2.5 pb-1.5 text-xs text-foreground-muted">{t("busyHint")}</p>
      )}
    </div>
  )
}
