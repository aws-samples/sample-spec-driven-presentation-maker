// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlashTokenReflection — Text-derived chips for template/style tokens in chat input.
 */

"use client"

import { Star, X } from "lucide-react"
import { useTranslations } from "next-intl"
import { parseTokens, type PickerItem, type TokenMatch } from "@/lib/slashToken"

export interface SlashTokenReflectionProps {
  text: string
  items: PickerItem[]
  onRemove: (match: TokenMatch) => void
}

function TemplateTokenSwatch({ item }: { item: PickerItem }) {
  const colors = item.themeColors ?? {}
  const palette = [colors.accent1, colors.accent2, colors.accent3].filter(
    (color): color is string => Boolean(color),
  )

  return (
    <span
      className="flex h-3 w-5 shrink-0 items-center justify-end gap-px overflow-hidden rounded-sm border border-black/10 px-0.5"
      style={colors.background ? { backgroundColor: colors.background } : undefined}
      aria-hidden="true"
    >
      {palette.map((color, index) => (
        <span key={`${color}-${index}`} className="h-1 w-1 rounded-full ring-1 ring-black/10" style={{ backgroundColor: color }} />
      ))}
    </span>
  )
}

function StyleTokenMark({ item }: { item: PickerItem }) {
  return (
    <span className="grid h-3 w-5 shrink-0 place-items-center text-foreground-muted" aria-hidden="true">
      {item.pinned ? <Star className="h-3 w-3 fill-current" /> : <span className="text-[11px] font-medium leading-none">Aa</span>}
    </span>
  )
}

export function SlashTokenReflection({ text, items, onRemove }: SlashTokenReflectionProps) {
  const t = useTranslations("slashPicker")
  const matches = parseTokens(text)
  if (matches.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5 px-1 pb-2">
      {matches.map((match) => {
        const item = items.find((candidate) => candidate.kind === match.kind && candidate.name === match.name)
        // Before the catalogue has loaded nothing is known yet — don't flag every chip as unknown.
        const unknown = items.length > 0 && item == null
        return (
          <span
            key={`${match.start}-${match.end}`}
            title={unknown ? t("unknownName") : undefined}
            className={`flex min-h-7 items-center gap-1.5 rounded-md border bg-foreground/[0.03] px-2 py-1 motion-safe:animate-[card-in_.25s_ease-out] ${
              unknown ? "border-dashed border-foreground-muted" : "border-border"
            }`}
          >
            {item ? (
              item.kind === "template" ? <TemplateTokenSwatch item={item} /> : <StyleTokenMark item={item} />
            ) : (
              <span className="grid h-3 w-5 place-items-center text-[11px] text-foreground-muted" aria-hidden="true">?</span>
            )}
            <span className="text-[11px] uppercase text-foreground-muted">
              {t(match.kind === "template" ? "sectionTemplate" : "sectionStyle")}
            </span>
            <span className="max-w-40 truncate text-xs text-foreground">{match.name}</span>
            <button
              type="button"
              onClick={() => onRemove(match)}
              className="grid h-5 w-5 place-items-center rounded text-foreground-muted motion-safe:transition-colors hover:bg-foreground/[0.08] hover:text-foreground"
              aria-label={t("removeToken", {
                kind: t(match.kind === "template" ? "sectionTemplate" : "sectionStyle"),
                name: match.name,
              })}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        )
      })}
    </div>
  )
}
