// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * OutlineView v5 — "Slide Narrative" renderer.
 *
 * Single-column vertical stack. Each slide entry is a grid row:
 * number rail (36px) + card body.
 *
 * Card states:
 * - skeleton: dashed-border slim card (eyebrow slug + message only)
 * - enriched (active/done): solid border + shadow face with eyebrow, message,
 *   accent rule, what_to_say quote lead, and spec sheet (evidence / visual)
 * - active: inverted number chip in the rail
 *
 * No clipping: no aspect-ratio forcing, no absolute inset, no overflow-hidden.
 * All content flows naturally and grows with its content.
 *
 * @param props.content - Raw outline markdown string (null = empty state)
 */

"use client"

import { useEffect, useRef, useMemo } from "react"
import { FileText } from "lucide-react"
import { parseOutline, resolveStates } from "./outlineParser"
import type { OutlineEntry, SlideEntry, SectionEntry, ProseEntry, SlideState } from "./outlineParser"
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
// Mini SVG icons for spec sheet labels
// ---------------------------------------------------------------------------

function EvidenceIcon(): React.ReactElement {
  return (
    <svg className="w-3 h-3 stroke-current opacity-75" fill="none" strokeWidth="1.4" strokeLinecap="round" viewBox="0 0 16 16">
      <path d="M2 13h12M4 9l3 3 5-7" />
    </svg>
  )
}

function VisualIcon(): React.ReactElement {
  return (
    <svg className="w-3 h-3 stroke-current opacity-75" fill="none" strokeWidth="1.4" strokeLinecap="round" viewBox="0 0 16 16">
      <rect x="2" y="3" width="12" height="10" rx="2" />
      <circle cx="5.5" cy="6.5" r="1.2" />
      <path d="M14 10l-3-3-5 5" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Skeleton Slide (dashed slim card)
// ---------------------------------------------------------------------------

function SkeletonSlide({ slide }: { slide: SlideEntry }): React.ReactElement {
  return (
    <div className="rounded-lg border border-dashed border-foreground/20 px-4 py-3 flex flex-col gap-1">
      {/* Eyebrow: slug */}
      <span className="font-mono text-[11px] tracking-[0.08em] text-foreground-secondary/60">
        {slide.slug}
      </span>
      {/* Message */}
      <p className="text-base font-medium leading-[1.65] text-foreground">
        {slide.message || slide.slug}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Enriched Slide (solid border + shadow face)
// ---------------------------------------------------------------------------

function EnrichedSlide({ slide, state }: {
  slide: SlideEntry
  state: SlideState
}): React.ReactElement {
  const t = useTranslations("outline")
  const whatToSay = slide.subItems.find((s) => s.key === "what_to_say")
  const evidence = slide.subItems.find((s) => s.key === "evidence")
  const visual = slide.subItems.find((s) => s.key === "what_to_show")
  const notes = slide.subItems.find((s) => s.key === "notes")

  const frameClasses = state === "active"
    ? "border-foreground/60 shadow-[0_6px_24px_oklch(0_0_0/0.14)]"
    : "border-foreground/12"

  return (
    <div className="flex flex-col gap-1.5">
      {/* Slide face */}
      <div className={`rounded-xl border border-solid ${frameClasses} bg-background px-5 py-4 flex flex-col`}>
        {/* Eyebrow: slug */}
        <span className="font-mono text-[11px] tracking-[0.08em] text-foreground-secondary/60">
          {slide.slug}
        </span>

        {/* Message */}
        <p className="mt-1 text-base font-medium leading-[1.65] text-foreground">
          {slide.message || slide.slug}
        </p>

        {/* Accent rule */}
        <div className="w-11 h-[3px] rounded-sm bg-foreground/85 my-3" aria-hidden="true" />

        {/* what_to_say quote lead */}
        {whatToSay && (
          <p className="text-sm leading-relaxed text-foreground-secondary">
            <span className="text-foreground-secondary/50" aria-hidden="true">{"\u201C"}</span>
            {renderValue(whatToSay.value)}
            <span className="text-foreground-secondary/50" aria-hidden="true">{"\u201D"}</span>
          </p>
        )}

        {/* Spec sheet */}
        {(evidence || visual) && (
          <div className="mt-3.5 border-t border-foreground/15">
            {evidence && (
              <div className="grid grid-cols-[92px_1fr] gap-3 py-2 border-b border-dashed border-foreground/10 items-baseline">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground-secondary/60">
                  <EvidenceIcon />
                  {t("evidence")}
                </span>
                <p className="text-sm text-foreground leading-relaxed">
                  {renderValue(evidence.value)}
                </p>
              </div>
            )}
            {visual && (
              <div className="grid grid-cols-[92px_1fr] gap-3 py-2 border-b border-dashed border-foreground/10 items-baseline last:border-b-0">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground-secondary/60">
                  <VisualIcon />
                  {t("visual")}
                </span>
                <p className="text-sm text-foreground leading-relaxed">
                  {renderValue(visual.value)}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Notes band (outside the face) */}
      {notes && (
        <div className="px-4 py-2 rounded border border-foreground/6 bg-foreground/[0.02]">
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
// Section entry (full-width divider)
// ---------------------------------------------------------------------------

function SectionDivider({ section }: { section: SectionEntry }): React.ReactElement {
  return (
    <div className="col-span-full" data-entry-type="section">
      <h2 className="text-sm font-semibold text-foreground/70 tracking-[-0.015em] border-b border-foreground/8 pb-2 mt-6 mb-2">
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

  const { entries, stateMap } = useMemo(() => {
    if (!content) return { entries: [] as OutlineEntry[], stateMap: new Map<number, SlideState>() }
    const parsed = parseOutline(content)
    return {
      entries: parsed,
      stateMap: resolveStates(parsed),
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

  return (
    <div className="document-surface flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      <div className="max-w-2xl mx-auto flex flex-col gap-2.5">
        {entries.map((entry, i) => {
          if (entry.type === "section") {
            return <SectionDivider key={`section-${i}`} section={entry} />
          }
          if (entry.type === "prose") {
            return <ProseBlock key={`prose-${i}`} entry={entry} />
          }

          // Slide entry
          slideCounter++
          const state = stateMap.get(i) ?? "skeleton"
          const isActive = state === "active"
          const currentNumber = slideCounter

          return (
            <div
              key={entry.slug}
              ref={isActive ? activeRef : undefined}
              className="outline-node-enter grid items-start gap-2.5"
              style={{
                gridTemplateColumns: "36px 1fr",
                "--stagger": `${currentNumber * 50}ms`,
              } as React.CSSProperties}
              data-state={state}
              data-slide-slug={entry.slug}
            >
              {/* Number rail */}
              <span
                className={`text-right tabular-nums text-lg font-semibold pt-3 ${
                  isActive
                    ? "bg-foreground text-background rounded px-2 py-0.5 justify-self-end"
                    : "text-foreground-secondary/40"
                }`}
              >
                {currentNumber}
              </span>

              {/* Card body */}
              {state === "skeleton" ? (
                <SkeletonSlide slide={entry} />
              ) : (
                <EnrichedSlide slide={entry} state={state} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
