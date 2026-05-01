// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ModeSelector — Kiro-inspired Vibe/Spec mode selection cards.
 * Shown on the initial chat screen before any messages are sent.
 */

"use client"

import { MessageCircle, ClipboardList, Link, FileText, Mic, Target, LayoutTemplate, Sparkles } from "lucide-react"

interface ModeSelectorProps {
  value: "spec" | "vibe"
  onChange: (mode: "spec" | "vibe") => void
}

const modes = [
  {
    key: "vibe" as const,
    label: "Vibe",
    icon: MessageCircle,
    description: "Drop materials, get slides. Minimal interaction for quick conversions.",
    greatFor: [
      { icon: Link, text: "URLs & articles → slides" },
      { icon: FileText, text: "Papers & docs → summary deck" },
      { icon: Mic, text: "Meeting notes → presentation" },
    ],
    accentSide: "left" as const,
  },
  {
    key: "spec" as const,
    label: "Spec",
    icon: ClipboardList,
    description: "Plan first, then build. Refine requirements through dialogue before composing.",
    greatFor: [
      { icon: Target, text: "Proposals & pitch decks" },
      { icon: LayoutTemplate, text: "Projects needing structure" },
      { icon: Sparkles, text: "Polished, precise presentations" },
    ],
    accentSide: "right" as const,
  },
] as const

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
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
                  ? "bg-brand-teal-soft border border-brand-teal/40 shadow-[0_0_12px_oklch(0.75_0.14_185_/_8%)]"
                  : "bg-white/[0.03] border border-white/[0.06] hover:border-white/[0.12] hover:bg-white/[0.05]"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <m.icon className={`h-4 w-4 ${active ? "text-brand-teal" : "text-foreground-muted"}`} />
                <span className={`text-[13px] font-semibold ${active ? "text-brand-teal" : "text-foreground-muted"}`}>
                  {m.label}
                </span>
              </div>
              <p className={`text-[11px] leading-relaxed ${active ? "text-foreground-secondary" : "text-foreground-muted"}`}>
                {m.description}
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
        <p className="text-[11px] font-medium text-foreground-muted tracking-wide uppercase mb-2">Great for</p>
        {selected.greatFor.map((item, i) => (
          <div key={i} className="flex items-center gap-2">
            <item.icon className="h-3 w-3 text-brand-teal flex-none" />
            <span className="text-[12px] text-foreground-secondary">{item.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
