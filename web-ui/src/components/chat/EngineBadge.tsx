// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useTranslations } from "next-intl"

import type { KiroSessionEngine } from "@/lib/local/kiro-sessions.types"

/** Which agent engine saved a kiro session: a small "V3" / "V2" pill (Local mode only). */
export function EngineBadge({ engine }: { engine: KiroSessionEngine }) {
  const t = useTranslations("sessionPicker")
  const name = engine.toUpperCase()
  const label = t("engineBadgeLabel", { engine: name })
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="inline-flex flex-none items-center rounded-full border border-border px-1.5 text-[11px] font-medium leading-4 text-foreground-muted"
    >
      {name}
    </span>
  )
}
