// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ModeSelector — Vibe/Spec working-style chip in the composer's footer row.
 * Shown on the initial chat screen before any messages are sent. The chip names the
 * current style; its menu explains both.
 */

"use client"

import { ChevronDown, Compass, Zap } from "lucide-react"
import { useTranslations } from "next-intl"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface ModeSelectorProps {
  value: "spec" | "vibe"
  onChange: (mode: "spec" | "vibe") => void
}

// Labels ("Vibe"/"Spec") are product names; supporting copy is localized.
const modes = [
  { key: "spec" as const, label: "Spec", icon: Compass, pathKey: "specPath", summaryKey: "specSummary" },
  { key: "vibe" as const, label: "Vibe", icon: Zap, pathKey: "vibePath", summaryKey: "vibeSummary" },
] as const

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  const t = useTranslations("modeSelector")
  const current = modes.find((m) => m.key === value) ?? modes[0]
  const Icon = current.icon

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t("chipLabel", { mode: current.label })}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-sm font-medium text-foreground-secondary hover:border-border-hover hover:text-foreground data-[state=open]:border-border-hover data-[state=open]:text-foreground motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          {current.label}
          <ChevronDown className="h-3 w-3 text-foreground-muted" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72 p-1.5">
        <DropdownMenuLabel className="text-xs font-medium text-foreground-muted">{t("chooseWorkingStyle")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value} onValueChange={(v) => onChange(v === "vibe" ? "vibe" : "spec")}>
          {modes.map((mode) => (
            <DropdownMenuRadioItem key={mode.key} value={mode.key} className="items-start rounded-lg py-2.5">
              <span className="flex flex-col gap-0.5">
                <span className="flex items-baseline gap-2">
                  <span className="text-sm font-semibold text-foreground">{mode.label}</span>
                  <span className="text-xs text-foreground-muted">{t(mode.pathKey)}</span>
                </span>
                <span className="text-xs leading-snug text-foreground-secondary">{t(mode.summaryKey)}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
