// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * HtmlFormatPill — "Build as HTML" toggle on the initial chat screen.
 *
 * Holds no state of its own: it is pressed exactly when the input contains
 * `@format:html`, and pressing it adds or removes that token. PPTX (the
 * default) sends nothing.
 */

"use client"

import { Check, CodeXml } from "lucide-react"
import { useTranslations } from "next-intl"
import { hasFormatToken, toggleFormatToken } from "@/lib/slashToken"

interface HtmlFormatPillProps {
  /** Current chat input text. */
  text: string
  /** Replace the chat input with the toggled text. */
  onChange: (next: string) => void
}

export function HtmlFormatPill({ text, onChange }: HtmlFormatPillProps) {
  const t = useTranslations("htmlFormatPill")
  const pressed = hasFormatToken(text)

  return (
    <button
      type="button"
      aria-pressed={pressed}
      title={t("hint")}
      onClick={() => onChange(toggleFormatToken(text))}
      className={`mt-3 inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal ${
        pressed
          ? "border-foreground bg-foreground/[0.06] text-foreground"
          : "border-border text-foreground-secondary hover:border-border-hover hover:text-foreground"
      }`}
    >
      {pressed ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <CodeXml className="h-3.5 w-3.5" aria-hidden="true" />}
      {t("buildAsHtml")}
    </button>
  )
}
