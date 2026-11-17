// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChoiceChip — a style or template choice in the composer's footer row on the initial chat
 * screen. Dashed while nothing is chosen (the agent picks); solid with the name once chosen.
 *
 * Holds no state of its own: the choice is the input's first `@style:` / `@template:` token,
 * so a choice made with `/` or removed by hand shows here too. Opening it shows a gallery —
 * a cover preview per style, the theme per template — with search and an "agent picks" card.
 */

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Popover } from "radix-ui"
import { LayoutTemplate, Palette, Search, Sparkles, Star, X } from "lucide-react"
import { useTranslations } from "next-intl"
import { buildCoverDoc } from "@/components/StyleSlidePreview"
import { setKindToken, tokenName, type PickerItem } from "@/lib/slashToken"

type ChoiceKind = "style" | "template"

interface ChoiceChipProps {
  kind: ChoiceKind
  /** Current chat input text. */
  text: string
  /** Replace the chat input with the changed text. */
  onChange: (next: string) => void
  /** Catalogue (styles and templates; other kinds are ignored). */
  items: PickerItem[]
  loading: boolean
  /** Load the catalogue (called when the gallery opens). */
  onOpen: () => void
}

const SLIDE_WIDTH = 1920
/** Gallery columns (desktop); arrow keys move by a row. */
const COLS = 3

export function ChoiceChip({ kind, text, onChange, items, loading, onOpen }: ChoiceChipProps) {
  const t = useTranslations("choiceChip")
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const current = tokenName(text, kind)
  const Icon = kind === "style" ? Palette : LayoutTemplate
  const K = kind === "style" ? "Style" : "Template"

  const candidates = useMemo(() => {
    const q = query.trim().toLowerCase()
    return items
      .filter((item) => item.kind === kind)
      .filter((item) => !q || item.name.toLowerCase().includes(q) || item.description.toLowerCase().includes(q))
      .sort((a, b) => Number(b.pinned) - Number(a.pinned))
  }, [items, kind, query])
  // Index 0 is "agent picks"; the cards follow.
  const count = candidates.length + 1

  const choose = (name: string | null) => {
    onChange(setKindToken(text, kind, name))
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : e.key === "ArrowDown" ? COLS : e.key === "ArrowUp" ? -COLS : 0
    if (step) {
      e.preventDefault()
      setActive((i) => Math.max(0, Math.min(count - 1, i + step)))
    } else if (e.key === "Enter") {
      e.preventDefault()
      choose(active === 0 ? null : candidates[active - 1]?.name ?? null)
    }
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          onOpen()
          setQuery("")
          const at = current ? candidates.findIndex((c) => c.name === current) : -1
          setActive(at >= 0 ? at + 1 : 0)
        }
      }}
    >
      <span className={`inline-flex h-8 items-center rounded-full border text-sm motion-safe:transition-colors ${
        current
          ? "border-border-hover text-foreground"
          : "border-dashed border-border-hover text-foreground-muted hover:text-foreground-secondary"
      }`}>
        <Popover.Trigger asChild>
          <button
            type="button"
            aria-label={current ? t("chosen", { kind: t(kind), name: current }) : t(`choose${K}`)}
            className={`inline-flex h-full min-w-0 items-center gap-1.5 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal ${current ? "pl-3 pr-1" : "px-3"}`}
          >
            <Icon className="h-3.5 w-3.5 flex-none" aria-hidden="true" />
            <span className={current ? "max-w-[160px] truncate font-medium" : ""}>{current ?? t(kind)}</span>
          </button>
        </Popover.Trigger>
        {current && (
          <button
            type="button"
            onClick={() => choose(null)}
            aria-label={t(`clear${K}`)}
            className="mr-1 grid h-6 w-6 place-items-center rounded-full text-foreground-muted hover:bg-background-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        )}
      </span>

      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={8}
          collisionPadding={12}
          onKeyDown={onKeyDown}
          className="z-50 flex max-h-[min(480px,var(--radix-popover-content-available-height))] w-[720px] max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-2xl border border-border-hover bg-popover shadow-[var(--shadow-float)] motion-safe:animate-[slash-pop-in_160ms_ease-out]"
        >
          <div className="flex flex-none items-center gap-2 border-b border-border px-3 py-2">
            <Search className="h-4 w-4 flex-none text-foreground-muted" aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(e) => { setQuery(e.target.value); setActive(0) }}
              placeholder={t(`search${K}`)}
              aria-label={t(`search${K}`)}
              className="h-8 min-w-0 flex-1 bg-transparent text-sm focus:outline-none placeholder:text-foreground-muted"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
          <div role="listbox" aria-label={t(kind)} className="grid grid-cols-2 gap-2.5 p-3 sm:grid-cols-3">
            <AutoCard selected={!current} active={active === 0} onHover={() => setActive(0)} onChoose={() => choose(null)} />
            {loading && candidates.length === 0 && (
              <p className="col-span-full px-1 py-2 text-sm text-foreground-muted">{t("loading")}</p>
            )}
            {!loading && candidates.length === 0 && (
              <p className="col-span-full px-1 py-2 text-sm text-foreground-muted">{t("noMatch")}</p>
            )}
            {candidates.map((item, i) => (
              <ChoiceCard
                key={`${item.kind}-${item.name}`}
                item={item}
                selected={item.name === current}
                active={active === i + 1}
                onHover={() => setActive(i + 1)}
                onChoose={() => choose(item.name)}
              />
            ))}
          </div>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

function cardClass(selected: boolean, active: boolean): string {
  return `group flex flex-col overflow-hidden rounded-xl border text-left motion-safe:transition-[border-color,box-shadow] focus-visible:outline-none ${
    selected ? "border-foreground/60" : active ? "border-border-hover" : "border-border"
  } ${active ? "shadow-[var(--shadow-card)] ring-1 ring-foreground/20" : ""}`
}

function AutoCard({ selected, active, onHover, onChoose }: { selected: boolean; active: boolean; onHover: () => void; onChoose: () => void }) {
  const t = useTranslations("choiceChip")
  const ref = useScrollIntoViewWhen(active)
  return (
    <button ref={ref} type="button" role="option" aria-selected={selected} onMouseMove={onHover} onClick={onChoose} className={cardClass(selected, active)}>
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

function ChoiceCard({ item, selected, active, onHover, onChoose }: { item: PickerItem; selected: boolean; active: boolean; onHover: () => void; onChoose: () => void }) {
  const custom = useTranslations("stylePicker")
  const ref = useScrollIntoViewWhen(active)
  return (
    <button ref={ref} type="button" role="option" aria-selected={selected} onMouseMove={onHover} onClick={onChoose} className={cardClass(selected, active)}>
      <span className="block aspect-video w-full overflow-hidden border-b border-border bg-foreground/[0.02]">
        {item.kind === "style" ? <StyleThumb item={item} /> : <TemplateThumb item={item} />}
      </span>
      <span className="px-3 py-2">
        <span className="flex min-w-0 items-center gap-1.5">
          {item.pinned && <Star className="h-3 w-3 flex-none fill-current text-foreground-secondary" aria-hidden="true" />}
          <span className="truncate text-sm font-medium text-foreground">{item.name}</span>
          {item.source === "user" && <span className="flex-none text-[11px] text-foreground-muted">{custom("custom")}</span>}
        </span>
        {item.description && <span className="block truncate text-xs text-foreground-muted">{item.description}</span>}
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
function TemplateThumb({ item }: { item: PickerItem }) {
  const colors = item.themeColors ?? {}
  const palette = [colors.accent1, colors.accent2, colors.accent3, colors.accent4, colors.accent5].filter((c): c is string => Boolean(c))
  return (
    <span className="relative flex h-full w-full flex-col justify-between p-3" style={colors.background ? { backgroundColor: colors.background } : undefined}>
      <span
        className="text-xl font-semibold leading-none"
        style={{ ...(colors.text ? { color: colors.text } : {}), ...(item.fonts?.halfwidth ? { fontFamily: item.fonts.halfwidth } : {}) }}
      >
        Aa
      </span>
      {palette.length > 0 && (
        <span className="flex h-1.5 w-full overflow-hidden rounded-full" aria-hidden="true">
          {palette.map((color, i) => <span key={`${color}-${i}`} className="h-full flex-1" style={{ backgroundColor: color }} />)}
        </span>
      )}
    </span>
  )
}

function useScrollIntoViewWhen(active: boolean) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (active) ref.current?.scrollIntoView?.({ block: "nearest" })
  }, [active])
  return ref
}
