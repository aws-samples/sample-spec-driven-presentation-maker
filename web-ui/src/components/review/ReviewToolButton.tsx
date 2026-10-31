// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** ReviewToolButton — the "Comment (C)" toggle in the preview header; filled with the annotation colour while on. */

"use client"

import { MessageSquarePlus } from "lucide-react"
import { useTranslations } from "next-intl"

export function ReviewToolButton({ on, onClick }: { on: boolean; onClick: () => void }) {
  const t = useTranslations("review")
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      title={t("toolTitle")}
      className={`mr-1 inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs transition-colors ${
        on ? "border-transparent bg-human text-human-ink" : "border-border-hover text-foreground hover:bg-background-hover"
      }`}
    >
      <MessageSquarePlus className="h-3.5 w-3.5" />
      {t("tool")}
      <kbd className={`rounded border px-1 py-px font-mono text-[11px] leading-none ${on ? "border-black/20 text-human-ink" : "border-border-hover text-muted-foreground"}`}>C</kbd>
    </button>
  )
}
