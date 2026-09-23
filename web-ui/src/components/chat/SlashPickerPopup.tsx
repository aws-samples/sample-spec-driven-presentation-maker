// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlashPickerPopup — Portal-based template/style autocomplete presentation.
 */

"use client"

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Star } from "lucide-react"
import { useTranslations } from "next-intl"
import { buildCoverDoc } from "@/components/StyleSlidePreview"
import { useIsMobile } from "@/hooks/UseMobile"
import type { PickerItem, PickerKind } from "@/lib/slashToken"

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
  loading: boolean
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  /** Input frame to align with (falls back to the textarea). The popup never exceeds its width. */
  anchorRef?: React.RefObject<HTMLElement | null>
  listboxId: string
}

/** Gap between the preview panel and the list (Tailwind `gap-2`). */
const PREVIEW_GAP = 8

const SLIDE_WIDTH = 1920
const SLIDE_HEIGHT = 1080
const PREVIEW_WIDTH = 240
const PREVIEW_SCALE = PREVIEW_WIDTH / SLIDE_WIDTH

function paletteFor(item: PickerItem, limit = 5): string[] {
  const colors = item.themeColors ?? {}
  return [colors.accent1, colors.accent2, colors.accent3, colors.accent4, colors.accent5]
    .filter((color): color is string => Boolean(color))
    .slice(0, limit)
}

function TemplateSwatch({ item }: { item: PickerItem }) {
  const colors = item.themeColors ?? {}
  const palette = paletteFor(item)

  return (
    <span
      className="flex h-5 w-11 shrink-0 items-center gap-0.5 overflow-hidden rounded border border-black/10 px-1"
      style={colors.background ? { backgroundColor: colors.background } : undefined}
      aria-hidden="true"
    >
      <span className="mr-auto text-[11px] font-medium" style={colors.text ? { color: colors.text } : undefined}>
        Aa
      </span>
      {palette.map((color, index) => (
        <span key={`${color}-${index}`} className="h-1 w-1 shrink-0 rounded-full ring-1 ring-black/10" style={{ backgroundColor: color }} />
      ))}
    </span>
  )
}

function StyleIdentifier({ pinned }: { pinned: boolean }) {
  return (
    <span className="grid h-5 w-11 shrink-0 place-items-center" aria-hidden="true">
      {pinned && <Star className="h-3.5 w-3.5 fill-current text-foreground-secondary" />}
    </span>
  )
}

function DebouncedStylePreview({ item }: { item: PickerItem }) {
  const t = useTranslations("slashPicker")
  const [previewDoc, setPreviewDoc] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!item.html) return
    const timer = window.setTimeout(() => setPreviewDoc(buildCoverDoc(item.html ?? "")), 120)
    return () => window.clearTimeout(timer)
  }, [item.html])

  return (
    <>
      <div className="aspect-video w-60 overflow-hidden bg-foreground/[0.02]">
        {previewDoc && (
          <iframe
            srcDoc={previewDoc}
            title={t("previewAlt", { name: item.name })}
            sandbox=""
            onLoad={() => setLoaded(true)}
            className={`pointer-events-none border-0 motion-safe:transition-opacity motion-safe:duration-150 ${loaded ? "opacity-100" : "opacity-0"}`}
            style={{
              width: SLIDE_WIDTH,
              height: SLIDE_HEIGHT,
              transform: `scale(${PREVIEW_SCALE})`,
              transformOrigin: "top left",
            }}
          />
        )}
      </div>
      <PreviewCaption item={item} />
    </>
  )
}

function TemplatePreview({ item }: { item: PickerItem }) {
  const t = useTranslations("slashPicker")
  const colors = item.themeColors ?? {}
  const palette = paletteFor(item)
  const fonts = [item.fonts?.halfwidth, item.fonts?.fullwidth].filter(Boolean).join(" / ")
  const layoutCount = item.layoutCount

  return (
    <>
      <div
        className="relative flex aspect-video w-60 items-start overflow-hidden bg-foreground/[0.02] p-4"
        style={colors.background ? { backgroundColor: colors.background } : undefined}
      >
        <span
          className="text-2xl font-semibold"
          style={{
            ...(colors.text ? { color: colors.text } : {}),
            ...(item.fonts?.halfwidth ? { fontFamily: item.fonts.halfwidth } : {}),
          }}
        >
          Aa
        </span>
        {palette.length > 0 && (
          <span className="absolute bottom-3 right-3 flex items-center gap-1" aria-hidden="true">
            {palette.map((color, index) => (
              <span key={`${color}-${index}`} className="h-2.5 w-2.5 rounded-full ring-1 ring-black/10" style={{ backgroundColor: color }} />
            ))}
          </span>
        )}
      </div>
      <div className="border-t border-border px-3 py-2">
        <p className="truncate text-sm font-medium text-foreground">{item.name}</p>
        {(fonts || layoutCount != null) && (
          <p className="truncate text-xs text-foreground-muted">
            {[fonts, layoutCount != null ? t("layouts", { count: layoutCount }) : ""].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>
    </>
  )
}

function PreviewCaption({ item }: { item: PickerItem }) {
  return (
    <div className="border-t border-border px-3 py-2">
      <p className="truncate text-sm font-medium text-foreground">{item.name}</p>
      {item.description && <p className="truncate text-xs text-foreground-muted">{item.description}</p>}
    </div>
  )
}

function PreviewPanel({ item }: { item: PickerItem | undefined }) {
  return (
    <aside className="w-60 shrink-0 overflow-hidden rounded-xl border border-border bg-popover shadow-lg">
      {!item ? (
        <div className="aspect-video w-60 bg-foreground/[0.02]" />
      ) : item.kind === "style" && item.html ? (
        <DebouncedStylePreview key={`${item.name}-${item.html}`} item={item} />
      ) : item.kind === "template" ? (
        <TemplatePreview item={item} />
      ) : (
        <>
          <div className="aspect-video w-60 bg-foreground/[0.02]" />
          <PreviewCaption item={item} />
        </>
      )}
    </aside>
  )
}

function Section({
  kind,
  items,
  activeIndex,
  allItems,
  listboxId,
  onMouseMove,
  onSelect,
}: {
  kind: PickerKind
  items: PickerItem[]
  activeIndex: number
  allItems: PickerItem[]
  listboxId: string
  onMouseMove: (index: number) => void
  onSelect: (item: PickerItem) => void
}) {
  const t = useTranslations("slashPicker")
  const custom = useTranslations("stylePicker")
  if (items.length === 0) return null

  return (
    <section>
      <div className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-foreground-muted">
        {t(kind === "template" ? "sectionTemplate" : "sectionStyle")}
      </div>
      {items.map((item) => {
        const index = allItems.indexOf(item)
        const active = index === activeIndex
        return (
          <button
            key={`${item.kind}-${item.name}`}
            id={slashOptionId(listboxId, index)}
            type="button"
            role="option"
            aria-selected={active}
            onMouseMove={() => onMouseMove(index)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onSelect(item)}
            className={`relative flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left motion-safe:transition-colors ${
              active ? "bg-foreground/[0.06]" : "bg-transparent hover:bg-foreground/[0.035]"
            }`}
          >
            {active && <span className="absolute inset-y-0 left-0 w-0.75 bg-foreground" aria-hidden="true" />}
            {item.kind === "template" ? <TemplateSwatch item={item} /> : <StyleIdentifier pinned={item.pinned} />}
            <span className="min-w-0 shrink-0 truncate text-sm font-medium text-foreground">{item.name}</span>
            {item.source === "user" && (
              <span className="shrink-0 text-[11px] font-medium text-foreground-muted">{custom("custom")}</span>
            )}
            {item.description && (
              <span className="min-w-0 flex-1 truncate text-xs text-foreground-muted">{item.description}</span>
            )}
          </button>
        )
      })}
    </section>
  )
}

export function SlashPickerPopup({
  open,
  query,
  items,
  filtered,
  activeIndex,
  onActiveIndexChange,
  onSelect,
  loading,
  textareaRef,
  anchorRef,
  listboxId,
}: SlashPickerPopupProps) {
  const t = useTranslations("slashPicker")
  const isMobile = useIsMobile()
  const mouseTargetIndexRef = useRef<number | null>(null)
  const activeItem = filtered[activeIndex]
  const activeId = activeItem ? slashOptionId(listboxId, activeIndex) : undefined

  useEffect(() => {
    if (!open || !activeId) return
    if (mouseTargetIndexRef.current === activeIndex) {
      mouseTargetIndexRef.current = null
      return
    }
    document.getElementById(activeId)?.scrollIntoView?.({ block: "nearest" })
  }, [activeId, activeIndex, open, query])

  if (!open || typeof document === "undefined") return null

  // The list sits exactly over the input frame (where the caret is); the
  // preview hangs off its left edge, over the main pane. The chat panel lives
  // at the right screen edge, so growing leftwards always stays on-screen —
  // unless the window itself is too narrow for the preview, then drop it.
  const anchorRect = (anchorRef?.current ?? textareaRef.current)?.getBoundingClientRect()
  const showPreview = !isMobile && (anchorRect?.left ?? 0) >= PREVIEW_WIDTH + PREVIEW_GAP
  const popupStyle = anchorRect
    ? {
        position: "fixed" as const,
        bottom: window.innerHeight - anchorRect.top + 8,
        right: window.innerWidth - anchorRect.right,
        width: anchorRect.width + (showPreview ? PREVIEW_WIDTH + PREVIEW_GAP : 0),
      }
    : { position: "fixed" as const, bottom: 16, left: 16 }
  const templateItems = filtered.filter((item) => item.kind === "template")
  const styleItems = filtered.filter((item) => item.kind === "style")
  const noMatches = !loading && (items.length === 0 || filtered.length === 0)

  const handleMouseMove = (index: number) => {
    if (index === activeIndex) return
    mouseTargetIndexRef.current = index
    onActiveIndexChange(index, "mouse")
  }

  return createPortal(
    <div
      className="z-50 flex gap-2 motion-safe:animate-[slash-pop-in_160ms_ease-out]"
      style={popupStyle}
      data-query={query || undefined}
    >
      {showPreview && <PreviewPanel item={activeItem} />}
      <div
        id={listboxId}
        role="listbox"
        aria-label={t("listLabel")}
        className="flex max-h-80 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
      >
        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <p className="px-3 py-3 text-sm text-foreground-muted">{t("loading")}</p>
          ) : noMatches ? (
            <p className="px-3 py-3 text-sm text-foreground-muted">{t("noMatch")}</p>
          ) : (
            <>
              <Section
                kind="template"
                items={templateItems}
                allItems={filtered}
                listboxId={listboxId}
                activeIndex={activeIndex}
                onMouseMove={handleMouseMove}
                onSelect={onSelect}
              />
              <Section
                kind="style"
                items={styleItems}
                allItems={filtered}
                listboxId={listboxId}
                activeIndex={activeIndex}
                onMouseMove={handleMouseMove}
                onSelect={onSelect}
              />
            </>
          )}
        </div>
        <div className="shrink-0 border-t border-border px-3 py-1.5 text-[11px] text-foreground-muted">
          {t("keyHint")}
        </div>
      </div>
    </div>,
    document.body,
  )
}
