// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ModeSelector — Kiro-inspired Vibe/Spec mode selection cards.
 * Shown on the initial chat screen before any messages are sent.
 */

"use client"

import { MessageCircle, ClipboardList, Link, FileText, Mic, Target, LayoutTemplate, Sparkles } from "lucide-react"
import { useTranslations } from "next-intl"

interface ModeSelectorProps {
  value: "spec" | "vibe"
  onChange: (mode: "spec" | "vibe") => void
}

// Labels ("Vibe"/"Spec") are product names, not translated; descriptions resolve via modeSelector.*
const modes = [
  {
    key: "vibe" as const,
    label: "Vibe",
    icon: MessageCircle,
    greatFor: [
      { icon: Link, textKey: "vibeFor1" },
      { icon: FileText, textKey: "vibeFor2" },
      { icon: Mic, textKey: "vibeFor3" },
    ] as const,
    accentSide: "left" as const,
  },
  {
    key: "spec" as const,
    label: "Spec",
    icon: ClipboardList,
    greatFor: [
      { icon: Target, textKey: "specFor1" },
      { icon: LayoutTemplate, textKey: "specFor2" },
      { icon: Sparkles, textKey: "specFor3" },
    ] as const,
    accentSide: "right" as const,
  },
] as const

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  const t = useTranslations("modeSelector")
  const selected = modes.find((m) => m.key === value)!

  return (
    <div className="w-full max-w-[340px] space-y-5">
      <div className="flex gap-3">
        {modes.map((m) => {
          const active = value === m.key
          return (
            <button
              key={m.key}
              onClick={() => onChange(m.key)}
              className={`flex-1 text-left rounded-xl p-3.5 transition-all cursor-pointer ${
                active
                  ? "bg-brand-teal-soft border border-brand-teal/40 shadow-[0_0_12px_var(--border-hover)]"
                  : "bg-foreground/[0.03] border border-border hover:border-border-hover hover:bg-foreground/[0.05]"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <m.icon className={`h-4 w-4 ${active ? "text-brand-teal" : "text-foreground-muted"}`} />
                <span className={`text-sm font-semibold ${active ? "text-brand-teal" : "text-foreground-muted"}`}>
                  {m.label}
                </span>
              </div>
              <p className={`text-xs leading-relaxed ${active ? "text-foreground-secondary" : "text-foreground-muted"}`}>
                {t(`${m.key}Description`)}
              </p>
            </button>
          )
        })}
      </div>

      {/* Great for — accent line on left for Vibe, right for Spec */}
      <div className={`py-1 space-y-2 pl-4 ${
        selected.accentSide === "left"
          ? "border-l-2 border-brand-teal/40"
          : "border-r-2 border-brand-teal/40"
      }`}>
        <p className="text-xs font-medium text-foreground-muted tracking-wide uppercase mb-2">{t("greatFor")}</p>
        {selected.greatFor.map((item, i) => (
          <div key={i} className="flex items-center gap-2">
            <item.icon className="h-3 w-3 text-brand-teal flex-none" />
            <span className="text-xs text-foreground-secondary">{t(item.textKey)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
