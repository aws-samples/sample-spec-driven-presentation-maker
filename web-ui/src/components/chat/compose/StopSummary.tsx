// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StopSummary — shown after a soft-stop of compose_slides.
 *
 * Displays the cancellation notice plus a collapsible per-group summary
 * of what each composer completed before stopping.
 */

"use client"

import { useState } from "react"
import { useTranslations } from "next-intl"
import { ChevronRight, Info } from "lucide-react"
import { STATE, C } from "./composeTokens"

export function StopSummary({ notice, summaries }: { notice?: string; summaries?: Record<string, string> }) {
  const t = useTranslations("compose")
  const [open, setOpen] = useState(false)
  const entries = summaries ? Object.entries(summaries) : []

  return (
    <div
      className="mx-3 mb-3 rounded-lg p-3 flex flex-col gap-2"
      style={{
        background: `color-mix(in oklch, ${STATE.retry} 6%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in oklch, ${STATE.retry} 18%, transparent)`,
      }}
    >
      {notice && (
        <div className="flex items-start gap-1.5">
          <Info className="flex-none h-3.5 w-3.5 mt-0.5" style={{ color: STATE.retry }} />
          <div className="text-xs leading-relaxed" style={{ color: C.fgLabel }}>
            {notice}
          </div>
        </div>
      )}
      {entries.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 text-[11px] font-medium uppercase hover:opacity-80 transition-opacity"
            style={{ color: C.smallLabel, letterSpacing: "0.14em" }}
          >
            <ChevronRight
              className="h-3 w-3 transition-transform duration-200"
              style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
            />
            {t("whatComposersDid", { count: entries.length })}
          </button>
          {open && (
            <ol className="mt-2 flex flex-col gap-2">
              {entries.map(([group, text]) => (
                <li key={group} className="flex flex-col gap-1">
                  <div className="text-[11px] font-medium" style={{ color: C.fgLabel }}>
                    {group}
                  </div>
                  <div
                    className="text-[11px] leading-relaxed whitespace-pre-wrap break-words"
                    style={{ color: C.fgDim }}
                  >
                    {text}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
