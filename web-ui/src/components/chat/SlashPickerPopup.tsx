// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlashPickerPopup — the `/` picker: a gallery of templates, styles and formats over the chat input.
 *
 * Its size does not follow the input: it is as wide as the window allows (up to 640px), sits
 * above the input when there is room and below it otherwise, and prefers to end at the input's
 * right edge, so beside a right-hand chat panel it opens over the deck. Focus stays in the
 * textarea; the text after `/` filters, and the kind buttons rewrite that text.
 */

"use client"

import { useLayoutEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Search } from "lucide-react"
import { useTranslations } from "next-intl"
import { SLASH_PANEL_MARGIN, galleryColumns, slashPanelWidth } from "@/lib/gridNav"
import { sectionTitleKey, splitQuery, type PickerItem, type PickerKind } from "@/lib/slashToken"
import { ChoiceCard } from "./ChoiceGallery"

/**
 * DOM id of the option at `index`. Index-based (not name-based) because quoted
 * template names may contain spaces, which are invalid in an ARIA IDREF.
 */
export function slashOptionId(listboxId: string, index: number): string {
  return `${listboxId}-opt-${index}`
}

export interface SlashPickerPopupProps {
  open: boolean
  query: string
  items: PickerItem[]
  filtered: PickerItem[]
  activeIndex: number
  onActiveIndexChange: (i: number, source: "key" | "mouse") => void
  onSelect: (item: PickerItem) => void
  /** Narrow to one kind (null: all). Omit to hide the kind buttons. */
  onKindChange?: (kind: PickerKind | null) => void
  loading: boolean
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  /** Input frame to place against (falls back to the textarea). */
  anchorRef?: React.RefObject<HTMLElement | null>
  listboxId: string
}

const KINDS: PickerKind[] = ["template", "style", "format"]
/** Gap between the input frame and the panel. */
const GAP = 8
const MAX_HEIGHT = 480
/** Below this much room above the input, open below it when there is more room there. */
const MIN_HEIGHT_ABOVE = 320

interface Placement {
  left: number
  width: number
  top?: number
  bottom?: number
  maxHeight: number
}

/** Where the panel goes for an anchor at `a` in a `vw` × `vh` window. */
export function placeSlashPanel(a: Pick<DOMRect, "left" | "right" | "top" | "bottom" | "width">, vw: number, vh: number): Placement {
  const M = SLASH_PANEL_MARGIN
  const width = slashPanelWidth(vw)
  // Centre on the anchor, but do not run past its right edge when the window has room
  // to the left (the chat panel sits at the right of the window).
  const maxLeft = Math.min(vw - M, Math.max(a.right, M + width)) - width
  const left = Math.max(M, Math.min(maxLeft, a.left + a.width / 2 - width / 2))
  const above = a.top - GAP - M
  const below = vh - a.bottom - GAP - M
  if (above >= MIN_HEIGHT_ABOVE || above >= below) {
    return { left, width, bottom: vh - a.top + GAP, maxHeight: Math.min(MAX_HEIGHT, above) }
  }
  return { left, width, top: a.bottom + GAP, maxHeight: Math.min(MAX_HEIGHT, below) }
}

function usePlacement(open: boolean, anchor: () => HTMLElement | null, panel: React.RefObject<HTMLElement | null>) {
  const [placement, setPlacement] = useState<Placement | null>(null)
  const anchorRef = useRef(anchor)
  anchorRef.current = anchor
  useLayoutEffect(() => {
    if (!open) return
    const measure = () => {
      const el = anchorRef.current()
      if (el) setPlacement(placeSlashPanel(el.getBoundingClientRect(), window.innerWidth, window.innerHeight))
    }
    const onScroll = (e: Event) => {
      if (e.target instanceof Node && panel.current?.contains(e.target)) return
      measure()
    }
    measure()
    window.addEventListener("resize", measure)
    window.addEventListener("scroll", onScroll, true)
    const el = anchorRef.current()
    const ro = typeof ResizeObserver !== "undefined" && el ? new ResizeObserver(measure) : null
    if (el) ro?.observe(el)
    return () => {
      window.removeEventListener("resize", measure)
      window.removeEventListener("scroll", onScroll, true)
      ro?.disconnect()
    }
  }, [open, panel])
  return placement
}

export function SlashPickerPopup({
  open,
  query,
  items,
  filtered,
  activeIndex,
  onActiveIndexChange,
  onSelect,
  onKindChange,
  loading,
  textareaRef,
  anchorRef,
  listboxId,
}: SlashPickerPopupProps) {
  const t = useTranslations("slashPicker")
  const panelRef = useRef<HTMLDivElement>(null)
  // The card under the pointer is already visible; only keyboard moves scroll.
  const [pointerIndex, setPointerIndex] = useState<number | null>(null)
  const placement = usePlacement(open, () => anchorRef?.current ?? textareaRef.current, panelRef)

  if (!open || typeof document === "undefined") return null

  const { kind: scope, term } = splitQuery(query)
  const kinds = KINDS.filter((kind) => items.some((item) => item.kind === kind))
  const cols = galleryColumns(placement?.width ?? slashPanelWidth(window.innerWidth))
  const sections = KINDS.map((kind) => ({ kind, items: filtered.filter((item) => item.kind === kind) })).filter((s) => s.items.length > 0)
  const noMatches = !loading && (items.length === 0 || filtered.length === 0)

  const style: React.CSSProperties = placement
    ? { position: "fixed", left: placement.left, width: placement.width, top: placement.top, bottom: placement.bottom, maxHeight: placement.maxHeight }
    : { position: "fixed", bottom: 16, left: 16, visibility: "hidden" }

  return createPortal(
    <div
      ref={panelRef}
      className="z-50 flex flex-col overflow-hidden rounded-2xl border border-border-hover bg-popover shadow-[var(--shadow-float)] motion-safe:animate-[slash-pop-in_160ms_ease-out]"
      style={style}
      data-query={query || undefined}
      data-placement={placement ? (placement.top !== undefined ? "below" : "above") : undefined}
    >
      <div className="flex flex-none items-center gap-1 border-b border-border px-2 py-1.5">
        {onKindChange && kinds.length > 1 && (
          <div className="flex items-center gap-0.5" role="group" aria-label={t("kindFilter")}>
            {[null, ...kinds].map((kind) => {
              const on = scope === kind
              return (
                <button
                  key={kind ?? "all"}
                  type="button"
                  tabIndex={-1}
                  aria-pressed={on}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onKindChange(kind)}
                  className={`h-7 rounded-full px-3 text-xs font-medium motion-safe:transition-colors ${
                    on ? "bg-foreground/[0.08] text-foreground" : "text-foreground-muted hover:bg-foreground/[0.04] hover:text-foreground-secondary"
                  }`}
                >
                  {kind ? t(sectionTitleKey(kind)) : t("all")}
                </button>
              )
            })}
          </div>
        )}
        {term && (
          <span className="ml-auto flex min-w-0 items-center gap-1.5 pr-2 text-xs text-foreground-secondary">
            <Search className="h-3.5 w-3.5 flex-none text-foreground-muted" aria-hidden="true" />
            <span className="truncate">{term}</span>
          </span>
        )}
      </div>

      <div id={listboxId} role="listbox" aria-label={t("listLabel")} className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {loading ? (
          <p className="py-3 text-sm text-foreground-muted">{t("loading")}</p>
        ) : noMatches ? (
          <p className="py-3 text-sm text-foreground-muted">{t("noMatch")}</p>
        ) : (
          sections.map((section) => {
            const headingId = `${listboxId}-${section.kind}`
            return (
              <section key={section.kind} role="group" aria-labelledby={headingId}>
                <h3 id={headingId} className="pb-1.5 pt-2.5 text-[11px] font-medium uppercase tracking-wider text-foreground-muted">
                  {t(sectionTitleKey(section.kind))}
                </h3>
                <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
                  {section.items.map((item) => {
                    const index = filtered.indexOf(item)
                    const active = index === activeIndex
                    return (
                      <ChoiceCard
                        key={`${item.kind}-${item.name}`}
                        id={slashOptionId(listboxId, index)}
                        item={item}
                        selected={false}
                        active={active}
                        ariaSelected={active}
                        keepFocus
                        compact
                        scrollOnActive={index !== pointerIndex}
                        onHover={() => {
                          if (index === activeIndex) return
                          setPointerIndex(index)
                          onActiveIndexChange(index, "mouse")
                        }}
                        onChoose={() => onSelect(item)}
                      />
                    )
                  })}
                </div>
              </section>
            )
          })
        )}
      </div>

      <div className="flex-none border-t border-border px-3 py-1.5 text-[11px] text-foreground-muted">
        {t("keyHint")}
      </div>
    </div>,
    document.body,
  )
}
