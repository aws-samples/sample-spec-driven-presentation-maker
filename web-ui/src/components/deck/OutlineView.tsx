// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * OutlineView — Slide-first outline renderer.
 *
 * Two adaptive modes:
 * - Light table (3-column slide sorter): when every slide has zero sub-items
 * - Detail view (full-width 16:9 slide cards): when any slide is enriched
 *
 * Design language: achromatic/Fraunces headings, ink frames with state-driven borders.
 * Frame states: skeleton=dashed, active=solid+shadow+inverted number, done=quiet.
 * TBD is dashed ink chip (not amber — amber is Data's agent color).
 *
 * @param props.content - Raw outline markdown string (null = empty state)
 */

"use client"

import { useEffect, useRef, useMemo } from "react"
import { FileText } from "lucide-react"
import { parseOutline, resolveStates, isLightTableMode, getSlideEntries } from "./outlineParser"
import type { OutlineEntry, SlideEntry, SectionEntry, ProseEntry, OutlineSubItem, SlideState, SubItemKey } from "./outlineParser"
import { renderColorSwatches } from "./colorSwatches"
import { useTranslations } from "next-intl"

/** Regex detecting [TBD] markers in sub-item values. */
const TBD_RE = /\[TBD(?::?\s*([^\]]*))?\]/g

/**
 * Render a sub-item value with [TBD] badges and HEX color swatches.
 */
function renderValue(value: string): (string | React.ReactElement)[] {
  const parts = value.split(TBD_RE)
  const elements: (string | React.ReactElement)[] = []

  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      const text = parts[i]
      if (text) {
        elements.push(...renderColorSwatches(text))
      }
    } else {
      const detail = parts[i]
      elements.push(
        <span
          key={`tbd-${i}`}
          className="inline-flex items-center gap-1 px-1.5 py-px rounded text-[11px] font-medium border border-dashed border-foreground/40 text-foreground/70"
        >
          TBD{detail ? `: ${detail}` : ""}
        </span>
      )
    }
  }

  return elements
}

// ---------------------------------------------------------------------------
// Slide Card (detail view)
// ---------------------------------------------------------------------------

/**
 * A full-width 16:9-proportioned slide card.
 * Face: title/message, what_to_say lead quote, Evidence, Visual, number+slug chrome.
 * Below: speaker notes band (notes sub-item).
 */
function SlideCard({ slide, state, slideNumber }: {
  slide: SlideEntry
  state: SlideState
  slideNumber: number
}): React.ReactElement {
  const t = useTranslations("outline")
  const whatToSay = slide.subItems.find((s) => s.key === "what_to_say")
  const evidence = slide.subItems.find((s) => s.key === "evidence")
  const visual = slide.subItems.find((s) => s.key === "what_to_show")
  const notes = slide.subItems.find((s) => s.key === "notes")

  const frameClasses = {
    skeleton: "border-dashed border-foreground/20",
    active: "border-solid border-foreground/60 shadow-[var(--shadow-slide)]",
    done: "border-solid border-foreground/12",
  }

  const numberClasses = {
    skeleton: "text-foreground/30",
    active: "bg-foreground text-background font-semibold",
    done: "text-foreground/40",
  }

  return (
    <div
      className="outline-node-enter"
      style={{ "--stagger": `${slideNumber * 50}ms` } as React.CSSProperties}
      data-state={state}
      data-slide-slug={slide.slug}
    >
      {/* Slide face — 16:9 proportioned */}
      <div
        className={`relative rounded-lg border overflow-hidden ${frameClasses[state]}`}
        style={{ aspectRatio: "16 / 9" }}
      >
        {/* Content area */}
        <div className="absolute inset-0 flex flex-col justify-between p-5 sm:p-6">
          {/* Title + message */}
          <div className="space-y-2">
            <h3
              className="text-sm sm:text-[15px] leading-snug tracking-[-0.015em]"
              style={{ fontWeight: "var(--document-display-weight)" } as React.CSSProperties}
            >
              {slide.message || slide.slug}
            </h3>

            {/* what_to_say as lead quote */}
            {whatToSay && (
              <blockquote className="border-l-2 border-foreground/15 pl-3 text-xs text-foreground-secondary leading-relaxed italic">
                {renderValue(whatToSay.value)}
              </blockquote>
            )}
          </div>

          {/* Evidence + Visual in the mid area */}
          {(evidence || visual) && (
            <div className="flex-1 flex flex-col justify-center gap-2 my-3">
              {evidence && (
                <div className="flex items-start gap-2">
                  <span className="text-[11px] uppercase tracking-[0.08em] text-foreground-secondary/60 font-medium flex-none w-14">
                    {t("evidence")}
                  </span>
                  <p className="text-xs text-foreground/70 leading-relaxed">
                    {renderValue(evidence.value)}
                  </p>
                </div>
              )}
              {visual && (
                <div className="flex items-start gap-2">
                  <span className="text-[11px] uppercase tracking-[0.08em] text-foreground-secondary/60 font-medium flex-none w-14">
                    {t("visual")}
                  </span>
                  <p className="text-xs text-foreground/70 leading-relaxed">
                    {renderValue(visual.value)}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Page chrome: number + slug */}
          <div className="flex items-center justify-end gap-2">
            <span className="text-[11px] text-foreground-secondary/50 tracking-wide">
              {slide.slug}
            </span>
            <span
              className={`inline-flex items-center justify-center w-5 h-5 rounded text-[11px] tabular-nums ${numberClasses[state]}`}
            >
              {slideNumber}
            </span>
          </div>
        </div>
      </div>

      {/* Speaker notes band (below the slide face) */}
      {notes && (
        <div className="mt-1.5 px-4 py-2 rounded border border-foreground/6 bg-foreground/[0.02]">
          <div className="flex items-start gap-2">
            <span className="text-[11px] uppercase tracking-[0.08em] text-foreground-secondary/50 font-medium flex-none">
              {t("notes")}
            </span>
            <p className="text-xs text-foreground-secondary leading-relaxed">
              {renderValue(notes.value)}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Light Table Card (compact 3-col sorter)
// ---------------------------------------------------------------------------

function LightTableCard({ slide, state, slideNumber }: {
  slide: SlideEntry
  state: SlideState
  slideNumber: number
}): React.ReactElement {
  const frameClasses = {
    skeleton: "border-dashed border-foreground/20",
    active: "border-solid border-foreground/60 shadow-[var(--shadow-card)]",
    done: "border-solid border-foreground/12",
  }

  const numberClasses = {
    skeleton: "text-foreground/30",
    active: "bg-foreground text-background font-semibold",
    done: "text-foreground/40",
  }

  return (
    <div
      className={`outline-node-enter rounded-lg border overflow-hidden flex flex-col ${frameClasses[state]}`}
      style={{
        "--stagger": `${slideNumber * 40}ms`,
        aspectRatio: "16 / 9",
      } as React.CSSProperties}
      data-state={state}
      data-slide-slug={slide.slug}
    >
      <div className="flex-1 flex flex-col justify-between p-3">
        <p className="text-xs font-medium text-foreground/80 leading-snug line-clamp-2">
          {slide.message || slide.slug}
        </p>
        <div className="flex items-center justify-between mt-auto pt-1">
          <span className="text-[11px] text-foreground-secondary/40 truncate max-w-[60%]">
            {slide.slug}
          </span>
          <span
            className={`inline-flex items-center justify-center w-4 h-4 rounded text-[11px] tabular-nums ${numberClasses[state]}`}
          >
            {slideNumber}
          </span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section entry (full-width divider)
// ---------------------------------------------------------------------------

function SectionDivider({ section }: { section: SectionEntry }): React.ReactElement {
  return (
    <div className="col-span-full" data-entry-type="section">
      <h2
        className="text-sm font-semibold text-foreground/70 tracking-[-0.015em] border-b border-foreground/8 pb-2 mt-6 mb-2"
        style={{ fontWeight: "var(--document-display-weight)" } as React.CSSProperties}
      >
        {section.title}
      </h2>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Prose entry
// ---------------------------------------------------------------------------

function ProseBlock({ entry }: { entry: ProseEntry }): React.ReactElement {
  return (
    <div className="col-span-full" data-entry-type="prose">
      <p className="text-sm text-foreground-secondary leading-relaxed">
        {renderColorSwatches(entry.text)}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface OutlineViewProps {
  content: string | null
}

export function OutlineView({ content }: OutlineViewProps): React.ReactElement {
  const t = useTranslations("outline")
  const activeRef = useRef<HTMLDivElement>(null)
  const prevActiveSlug = useRef<string | null>(null)

  const { entries, stateMap, lightTable } = useMemo(() => {
    if (!content) return { entries: [] as OutlineEntry[], stateMap: new Map<number, SlideState>(), lightTable: false }
    const parsed = parseOutline(content)
    return {
      entries: parsed,
      stateMap: resolveStates(parsed),
      lightTable: isLightTableMode(parsed),
    }
  }, [content])

  // Find the active slide for auto-scroll
  const activeSlug = useMemo(() => {
    for (const [i, state] of stateMap.entries()) {
      if (state === "active") {
        const entry = entries[i]
        if (entry.type === "slide") return entry.slug
      }
    }
    return null
  }, [entries, stateMap])

  // Auto-scroll to active slide when it changes.
  useEffect(() => {
    if (activeSlug !== null && activeSlug !== prevActiveSlug.current) {
      prevActiveSlug.current = activeSlug
      const timer = setTimeout(() => {
        activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
      }, 150)
      return () => clearTimeout(timer)
    }
  }, [activeSlug])

  // Empty state
  if (!content || entries.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-4">
          <FileText className="h-5 w-5 text-foreground-muted/30" />
        </div>
        <p className="text-sm text-foreground-muted">
          {t("emptyState")}
        </p>
      </div>
    )
  }

  // Track slide numbering across all entries
  let slideCounter = 0

  // Light-table mode: 3-column grid with section headings full-width
  if (lightTable) {
    return (
      <div className="document-surface flex-1 overflow-y-auto px-6 sm:px-8 py-6">
        <div className="max-w-4xl mx-auto">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" data-view="light-table">
            {entries.map((entry, i) => {
              if (entry.type === "section") {
                return <SectionDivider key={`section-${i}`} section={entry} />
              }
              if (entry.type === "prose") {
                return <ProseBlock key={`prose-${i}`} entry={entry} />
              }
              // Slide
              slideCounter++
              const state = stateMap.get(i) ?? "skeleton"
              return (
                <div
                  key={entry.slug}
                  ref={state === "active" ? activeRef : undefined}
                >
                  <LightTableCard
                    slide={entry}
                    state={state}
                    slideNumber={slideCounter}
                  />
                </div>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  // Detail mode: full-width slide cards
  slideCounter = 0
  return (
    <div className="document-surface flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      <div className="max-w-2xl mx-auto space-y-4">
        {entries.map((entry, i) => {
          if (entry.type === "section") {
            return <SectionDivider key={`section-${i}`} section={entry} />
          }
          if (entry.type === "prose") {
            return <ProseBlock key={`prose-${i}`} entry={entry} />
          }
          // Slide
          slideCounter++
          const state = stateMap.get(i) ?? "skeleton"
          return (
            <div
              key={entry.slug}
              ref={state === "active" ? activeRef : undefined}
            >
              <SlideCard
                slide={entry}
                state={state}
                slideNumber={slideCounter}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
