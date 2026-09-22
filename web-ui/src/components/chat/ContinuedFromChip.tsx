// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { GitBranch } from "lucide-react"
import { useLocale, useTranslations } from "next-intl"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"

interface ContinuedFromChipProps {
  origin: SessionOrigin
}

export function ContinuedFromChip({ origin }: ContinuedFromChipProps) {
  const t = useTranslations("continuedFrom")
  const locale = useLocale()
  const updated = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(origin.updatedAt))

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-full border border-border bg-background-raised px-3 text-xs text-foreground-secondary motion-safe:transition-colors hover:border-border-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
        >
          <GitBranch className="h-3.5 w-3.5 flex-none text-brand-teal" aria-hidden="true" />
          <span className="truncate">{t("chip", { title: origin.title })}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" sideOffset={6} className="max-w-sm space-y-1 motion-reduce:animate-none">
        <p className="break-all">{t("tooltipCwd", { cwd: origin.cwd })}</p>
        <p>{t("tooltipUpdated", { date: updated })}</p>
        <p className="font-medium">{t("tooltipImmutable")}</p>
      </TooltipContent>
    </Tooltip>
  )
}
