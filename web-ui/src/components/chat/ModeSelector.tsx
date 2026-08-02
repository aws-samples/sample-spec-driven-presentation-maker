// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ModeSelector — Editorial Vibe/Spec working-style selector.
 * Shown on the initial chat screen before any messages are sent.
 */

"use client"

import { useId } from "react"
import { Check } from "lucide-react"
import { useTranslations } from "next-intl"

interface ModeSelectorProps {
  value: "spec" | "vibe"
  onChange: (mode: "spec" | "vibe") => void
}

// Labels ("Vibe"/"Spec") are product names; supporting copy is localized.
const modes = [
  {
    key: "vibe" as const,
    label: "Vibe",
    pathKey: "vibePath",
    summaryKey: "vibeSummary",
  },
  {
    key: "spec" as const,
    label: "Spec",
    pathKey: "specPath",
    summaryKey: "specSummary",
  },
] as const

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  const t = useTranslations("modeSelector")
  const labelId = useId()

  return (
    <div className="w-full max-w-[340px]">
      <p
        id={labelId}
        className="mb-3 text-xs font-medium uppercase tracking-[0.08em] text-foreground-muted"
      >
        {t("chooseWorkingStyle")}
      </p>
      <div
        role="group"
        aria-labelledby={labelId}
        className="overflow-hidden rounded-xl border border-border"
      >
        {modes.map((mode, index) => {
          const active = value === mode.key
          return (
            <button
              key={mode.key}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(mode.key)}
              className={`relative grid min-h-[82px] w-full grid-cols-[92px_minmax(0,1fr)_44px] items-center gap-3 px-3.5 py-3 text-left transition-colors ${
                index > 0 ? "border-t border-border" : ""
              } ${
                active
                  ? "bg-foreground/[0.06]"
                  : "bg-transparent hover:bg-foreground/[0.035]"
              }`}
            >
              {active && (
                <span
                  className="absolute inset-y-0 left-0 w-[3px] bg-foreground"
                  aria-hidden="true"
                />
              )}
              <span className="flex flex-col items-start gap-1">
                <span className="text-lg font-semibold leading-none tracking-[-0.025em] text-foreground">
                  {mode.label}
                </span>
                <span className="text-xs font-medium uppercase tracking-[0.08em] text-foreground-muted">
                  {t(mode.pathKey)}
                </span>
              </span>
              <span className="text-sm leading-snug text-foreground-secondary">
                {t(mode.summaryKey)}
              </span>
              <span className="touch-target flex items-center justify-end" aria-hidden="true">
                <span
                  className={`grid h-5 w-5 place-items-center rounded-full border ${
                    active
                      ? "border-foreground bg-foreground text-background"
                      : "border-border-hover text-transparent"
                  }`}
                >
                  <Check className="h-3 w-3" />
                </span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
