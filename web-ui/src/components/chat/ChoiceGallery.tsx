// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChoiceGallery — the cards shared by the choice chips' gallery and the `/` picker:
 * a style shows its cover, a template its theme, a format its icon.
 */

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { CodeXml, Sparkles, Star } from "lucide-react"
import { useTranslations } from "next-intl"
import { buildCoverDoc } from "@/components/StyleSlidePreview"
import type { PickerItem } from "@/lib/slashToken"

const SLIDE_WIDTH = 1920

interface CardProps {
  /** Shown as the current choice (solid outline). */
  selected: boolean
  /** Keyboard / pointer highlight. */
  active: boolean
  /** `aria-selected` — the chosen card for the chips, the highlighted one for `/`. */
  ariaSelected: boolean
  onHover: () => void
  onChoose: () => void
  id?: string
  /** Keep focus where it is (the `/` picker types into the chat input). */
  keepFocus?: boolean
  /** Scroll into view when it becomes active (off for pointer-driven highlights). */
  scrollOnActive?: boolean
  /** Smaller caption: the name only, the description as a tooltip (the `/` picker). */
  compact?: boolean
}

function cardClass(selected: boolean, active: boolean): string {
  return `group flex min-w-0 flex-col overflow-hidden rounded-xl border text-left motion-safe:transition-[border-color,box-shadow] focus-visible:outline-none ${
    selected ? "border-foreground/60" : active ? "border-border-hover" : "border-border"
  } ${active ? "shadow-[var(--shadow-card)] ring-1 ring-foreground/20" : ""}`
}

function useCardButton({ active, onHover, onChoose, id, keepFocus, scrollOnActive = true, ariaSelected }: Omit<CardProps, "selected" | "compact">) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (active && scrollOnActive) ref.current?.scrollIntoView?.({ block: "nearest" })
  }, [active, scrollOnActive])
  return {
    ref,
    id,
    type: "button" as const,
    role: "option",
    "aria-selected": ariaSelected,
    tabIndex: keepFocus ? -1 : undefined,
    onMouseMove: onHover,
    onMouseDown: keepFocus ? (e: React.MouseEvent) => e.preventDefault() : undefined,
    onClick: onChoose,
  }
}

/** "Agent picks" — leaves the choice to the agent. */
export function AutoCard(props: CardProps) {
  const t = useTranslations("choiceChip")
  return (
    <button {...useCardButton(props)} className={cardClass(props.selected, props.active)}>
      <span className="grid aspect-video w-full place-items-center border-b border-dashed border-border-hover bg-foreground/[0.02] text-foreground-secondary">
        <Sparkles className="h-6 w-6" aria-hidden="true" />
      </span>
      <span className="px-3 py-2">
        <span className="block text-sm font-medium text-foreground">{t("auto")}</span>
        <span className="block truncate text-xs text-foreground-muted">{t("autoHint")}</span>
      </span>
    </button>
  )
}

export function ChoiceCard({ item, compact = false, ...props }: CardProps & { item: PickerItem }) {
  const custom = useTranslations("stylePicker")
  const slash = useTranslations("slashPicker")
  const format = item.kind === "format"
  const name = format ? slash("formatHtml") : item.name
  const description = format ? item.description || slash("formatHtmlDescription") : item.description
  return (
    <button
      {...useCardButton(props)}
      title={compact && description ? `${name} — ${description}` : undefined}
      className={cardClass(props.selected, props.active)}
    >
      <span className="relative block aspect-video w-full overflow-hidden border-b border-border bg-foreground/[0.02]">
        {item.kind === "style" ? <StyleThumb item={item} /> : item.kind === "template" ? <TemplateThumb item={item} compact={compact} /> : <FormatThumb />}
        {/* Compact captions keep their width for the name; the badge sits on the cover. */}
        {compact && item.source === "user" && (
          <span className="absolute right-1.5 top-1.5 rounded bg-background/85 px-1.5 py-0.5 text-[11px] font-medium leading-none text-foreground-secondary backdrop-blur-sm">
            {custom("custom")}
          </span>
        )}
      </span>
      <span className={`min-w-0 ${compact ? "px-2.5 py-1.5" : "px-3 py-2"}`}>
        <span className="flex min-w-0 items-center gap-1.5">
          {item.pinned && <Star className="h-3 w-3 flex-none fill-current text-foreground-secondary" aria-hidden="true" />}
          <span className="truncate text-sm font-medium text-foreground">{name}</span>
          {!compact && item.source === "user" && <span className="flex-none text-[11px] text-foreground-muted">{custom("custom")}</span>}
        </span>
        {description && !compact && <span className="block truncate text-xs text-foreground-muted">{description}</span>}
      </span>
    </button>
  )
}

/** The style's cover, rendered lazily (only once the card is on screen). */
function StyleThumb({ item }: { item: PickerItem }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [width, setWidth] = useState(0)
  const visible = width > 0
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const show = () => setWidth(el.clientWidth || 1)
    if (typeof IntersectionObserver === "undefined") { show(); return }
    const io = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) { show(); io.disconnect() } })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  const doc = useMemo(() => (visible && item.html ? buildCoverDoc(item.html) : null), [visible, item.html])
  return (
    <span ref={ref} className="block h-full w-full">
      {doc && (
        <iframe
          srcDoc={doc}
          title={item.name}
          sandbox=""
          tabIndex={-1}
          onLoad={() => setLoaded(true)}
          className={`pointer-events-none border-0 motion-safe:transition-opacity motion-safe:duration-200 ${loaded ? "opacity-100" : "opacity-0"}`}
          style={{ width: SLIDE_WIDTH, height: (SLIDE_WIDTH * 9) / 16, transform: `scale(${width / SLIDE_WIDTH})`, transformOrigin: "top left" }}
        />
      )}
    </span>
  )
}

/** The template's theme: background, text colour and font, accents. */
function TemplateThumb({ item, compact = false }: { item: PickerItem; compact?: boolean }) {
  const colors = item.themeColors ?? {}
  const palette = [colors.accent1, colors.accent2, colors.accent3, colors.accent4, colors.accent5].filter((c): c is string => Boolean(c))
  return (
    <span className={`relative flex h-full w-full flex-col justify-between ${compact ? "p-2.5" : "p-3"}`} style={colors.background ? { backgroundColor: colors.background } : undefined}>
      <span
        className={`${compact ? "text-base" : "text-xl"} font-semibold leading-none`}
        style={{ ...(colors.text ? { color: colors.text } : {}), ...(item.fonts?.halfwidth ? { fontFamily: item.fonts.halfwidth } : {}) }}
      >
        Aa
      </span>
      {palette.length > 0 && (
        <span className={`flex w-full overflow-hidden rounded-full ${compact ? "h-1" : "h-1.5"}`} aria-hidden="true">
          {palette.map((color, i) => <span key={`${color}-${i}`} className="h-full flex-1" style={{ backgroundColor: color }} />)}
        </span>
      )}
    </span>
  )
}

function FormatThumb() {
  return (
    <span className="grid h-full w-full place-items-center text-foreground-secondary" aria-hidden="true">
      <CodeXml className="h-7 w-7" />
    </span>
  )
}
