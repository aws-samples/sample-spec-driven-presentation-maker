// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ComposerNoteCard — a message between the orchestrator and a running composer (Cloud).
 *
 * `direction="to"`: the orchestrator's `message_composer` call. `direction="from"`: a
 * composer's `report_to_orchestrator` (the `composerNote` event, or a `<composer_note>`
 * in the history). Left-aligned on a muted surface, so it does not read as a user bubble.
 */

"use client"

import { ArrowRight, MessageSquare } from "lucide-react"
import { useTranslations } from "next-intl"

interface ComposerNoteCardProps {
  direction: "from" | "to"
  /** 1-based group of the compose_slides call. */
  group: number
  slugs?: string
  text: string
}

export function ComposerNoteCard({ direction, group, slugs, text }: ComposerNoteCardProps) {
  const t = useTranslations("composerNote")
  const Icon = direction === "to" ? ArrowRight : MessageSquare
  return (
    <div
      role="note"
      aria-label={t("aria", { group })}
      className="rounded-xl border border-border bg-foreground/[0.03] px-3 py-2"
    >
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-foreground-muted">
        <Icon className="h-3 w-3 flex-none" aria-hidden="true" />
        <span className="font-medium text-foreground-secondary">{t(direction, { group })}</span>
        {slugs && <span className="truncate">· {slugs}</span>}
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground/85">{text}</p>
    </div>
  )
}
