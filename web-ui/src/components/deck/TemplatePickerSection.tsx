// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * TemplatePickerSection — Header-like template picker for the Art Direction pane.
 *
 * Always rendered at the top of the shared scroll container (non-sticky),
 * independent of the style section's state machine below it.
 *
 * Selection model: the UI is an insertion device, not a state control —
 * clicking a card inserts a chat message; the agent is the only actor that
 * confirms a template (by writing deck.json). The confirmed template is
 * read back via `useCurrentTemplate` and shown with an accent border.
 */

"use client"

import { useEffect, useRef, useState } from "react"
import { Plus, Check } from "lucide-react"
import { useTranslations } from "next-intl"
import { fetchTemplates, type TemplateEntry } from "@/services/deckService"

const PULSE_MS = 600

/** Normalize a deck.json template value: "templates/corporate.pptx" → "corporate". */
function normalizeTemplateName(raw?: string | null): string | null {
  if (!raw) return null
  const name = raw.replace(/\.pptx$/, "").split("/").pop() || ""
  return name || null
}

export function TemplatePickerSection({ idToken, currentTemplate, onTemplateSelect }: {
  idToken?: string
  /** Raw template value from deck.json (e.g. "corporate.pptx"), null when unconfirmed. */
  currentTemplate?: string | null
  onTemplateSelect: (name: string, isChange: boolean) => void
}) {
  const t = useTranslations("templatePicker")
  const [templates, setTemplates] = useState<TemplateEntry[]>([])
  const [loading, setLoading] = useState(true)
  const loadedRef = useRef(false)
  const [pulsing, setPulsing] = useState<string | null>(null)
  const pulseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const current = normalizeTemplateName(currentTemplate)

  useEffect(() => {
    if (!idToken || loadedRef.current) return
    loadedRef.current = true
    let cancelled = false
    fetchTemplates(idToken).then((list) => {
      if (cancelled) return
      setTemplates(list)
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [idToken])

  useEffect(() => () => { if (pulseTimerRef.current) clearTimeout(pulseTimerRef.current) }, [])

  const handleClick = (name: string) => {
    onTemplateSelect(name, current != null)
    setPulsing(name)
    if (pulseTimerRef.current) clearTimeout(pulseTimerRef.current)
    pulseTimerRef.current = setTimeout(() => setPulsing(null), PULSE_MS)
  }

  // Order: user (custom) → builtin. Stable sort preserves the API order
  // within each group. Deliberately NOT current-first: reordering on
  // confirmation breaks spatial memory — the check icon, accent border,
  // and header label are the current-template indicators instead.
  const rank = (tpl: TemplateEntry) => (tpl.source === "user" ? 0 : 1)
  const sorted = [...templates].sort((a, b) => rank(a) - rank(b))

  return (
    <section className="px-6 pt-4 pb-4 border-b border-border">
      <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">{t("sectionTitle")}</h3>
        {current && (
          <span className="inline-flex items-center gap-1 text-xs text-brand-teal/90">
            <Check className="h-3 w-3" aria-hidden="true" />
            {t("currentLabel", { name: current })}
          </span>
        )}
      </div>
      {loading ? (
        <div className="flex gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-[180px] h-[68px] shrink-0 rounded-xl bg-foreground/[0.03] animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {sorted.map((tpl) => (
            <TemplatePickCard
              key={tpl.name}
              template={tpl}
              isCurrent={tpl.name === current}
              pulsing={tpl.name === pulsing}
              onClick={() => handleClick(tpl.name)}
            />
          ))}
        </div>
      )}
      </div>
    </section>
  )
}

function TemplatePickCard({ template, isCurrent, pulsing, onClick }: {
  template: TemplateEntry
  isCurrent: boolean
  pulsing: boolean
  onClick: () => void
}) {
  const t = useTranslations("templatePicker")
  const colors = template.theme_colors || {}
  const palette = [
    colors.accent1, colors.accent2, colors.accent3,
    colors.accent4, colors.accent5,
  ].filter(Boolean) as string[]
  const fonts = template.fonts || {}
  const fontDisplay = [fonts.halfwidth, fonts.fullwidth].filter(Boolean).join(" / ")
  const tooltip = [template.description, fontDisplay].filter(Boolean).join("\n") || template.name

  return (
    <button
      onClick={onClick}
      title={tooltip}
      aria-label={t("useTemplateAria", { name: template.name })}
      data-current={isCurrent || undefined}
      className={`group relative w-[180px] shrink-0 rounded-xl border text-left overflow-hidden transition-all duration-200 cursor-pointer ${
        isCurrent
          ? "border-brand-teal ring-1 ring-brand-teal/50 bg-brand-teal/[0.06]"
          : "border-border hover:border-border-hover bg-foreground/[0.02]"
      } ${pulsing ? "ring-2 ring-brand-teal/50" : ""}`}
    >
      {/* Theme strip — background + text color identity + palette */}
      <div
        className="h-8 w-full flex items-center px-2.5"
        style={colors.background ? { backgroundColor: colors.background } : undefined}
      >
        {colors.text && (
          <span className="text-[11px] font-medium opacity-70" style={{ color: colors.text }}>Aa</span>
        )}
        {palette.length > 0 && (
          <span className="flex items-center gap-1 ml-auto">
            {palette.map((c, i) => (
              <span key={i} className="w-2 h-2 rounded-full ring-1 ring-black/10" style={{ backgroundColor: c }} />
            ))}
          </span>
        )}
      </div>
      {/* Name row */}
      <div className={`px-2.5 pt-2 flex items-center gap-1.5 ${template.description ? "pb-0.5" : "pb-2"}`}>
        {isCurrent && <Check className="h-3 w-3 text-brand-teal shrink-0" aria-hidden="true" />}
        <span className={`text-xs font-medium truncate ${isCurrent ? "text-brand-teal" : ""}`}>{template.name}</span>
        {template.source === "user" && (
          <span className="text-[11px] text-brand-teal/70 font-medium shrink-0">{t("custom")}</span>
        )}
      </div>
      {/* Description — user notes influence template choice, so keep them visible */}
      {template.description && (
        <p className="px-2.5 pb-2 text-xs text-foreground-muted line-clamp-2 leading-snug">
          {template.description}
        </p>
      )}
      {/* Hover overlay — previews the click's meaning (insert into chat) */}
      <span className="absolute inset-0 flex items-center justify-center gap-1 rounded-xl bg-black/60 text-xs font-medium text-foreground opacity-0 group-hover:opacity-100 transition-opacity duration-150">
        <Plus className="h-3.5 w-3.5" />
        {t("useTemplate")}
      </span>
    </button>
  )
}
