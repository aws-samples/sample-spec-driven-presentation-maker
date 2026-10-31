// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewSlideCta — while the tool is off, hovering a slide offers "Comment (C)" at its
 * top-right corner, where the user is already looking (R1.2). The parent carries `group/slide`.
 */

"use client"

import { MessageSquarePlus } from "lucide-react"
import { useTranslations } from "next-intl"

export function ReviewSlideCta({ onClick }: { onClick: () => void }) {
  const t = useTranslations("review")
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onClick() }}
      title={t("ctaTitle")}
      className="group/cta pointer-events-none absolute right-3 top-3 z-20 inline-flex h-8 -translate-y-[3px] items-center gap-1.5 rounded-lg bg-background-raised/95 pl-2.5 pr-2 text-xs text-foreground opacity-0 shadow-[0_6px_18px_oklch(0_0_0/30%),0_0_0_1px_oklch(1_0_0/10%)] transition-[opacity,transform,background-color] duration-150 hover:bg-human hover:text-human-ink focus-visible:pointer-events-auto focus-visible:translate-y-0 focus-visible:opacity-100 group-hover/slide:pointer-events-auto group-hover/slide:translate-y-0 group-hover/slide:opacity-100"
    >
      <MessageSquarePlus className="h-3.5 w-3.5" />
      {t("tool")}
      <kbd className="rounded border border-border-hover px-1 py-px font-mono text-[11px] leading-none text-muted-foreground group-hover/cta:border-black/20 group-hover/cta:text-human-ink">C</kbd>
    </button>
  )
}
