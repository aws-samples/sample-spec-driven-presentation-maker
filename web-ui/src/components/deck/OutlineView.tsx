// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * OutlineView — Editorial timeline renderer for outline specs.
 *
 * Renders parsed outline data as a vertical timeline with three visual states:
 * - skeleton: table-of-contents only (ghost appearance)
 * - active: currently under review (pulsing node, accent border panel)
 * - done: already reviewed (subdued panel)
 *
 * Design language: Dark Editorial × Minimal Luxury, matching the spec-driven-presentation-maker
 * web-ui design system (oklch colors, brand-teal/brand-amber accents).
 *
 * @param props.content - Raw outline markdown string (null = empty state)
 */

"use client"

import { useEffect, useRef, useMemo } from "react"
import { FileText, BarChart3, Palette, StickyNote } from "lucide-react"
import { parseOutline, resolveStates } from "./outlineParser"
import type { OutlineSlide, OutlineSubItem, SlideState, SubItemKey } from "./outlineParser"
import { renderColorSwatches } from "./SpecStepNav"

/** Icon and display label for each sub-item key (excluding what_to_say which has no label). */
const SUB_ITEM_META: Record<Exclude<SubItemKey, "what_to_say">, { Icon: typeof BarChart3; label: string }> = {
  evidence: { Icon: BarChart3, label: "Evidence" },
  what_to_show: { Icon: Palette, label: "Visual" },
  notes: { Icon: StickyNote, label: "Notes" },
}

/** Regex detecting [TBD] markers in sub-item values. */
const TBD_RE = /\[TBD(?::?\s*([^\]]*))?\]/g

/**
 * Render a sub-item value with [TBD] badges and HEX color swatches.
 *
 * @param value - Raw sub-item value string
 * @returns Array of string and React elements
 */
function renderValue(value: string): (string | React.ReactElement)[] {
  // First pass: replace [TBD] with badges.
  const parts = value.split(TBD_RE)
  const elements: (string | React.ReactElement)[] = []

  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      // Normal text — apply color swatch rendering.
      const text = parts[i]
      if (text) {
        elements.push(...renderColorSwatches(text))
      }
    } else {
      // TBD capture group (detail text after colon, may be empty).
      const detail = parts[i]
      elements.push(
        <span
          key={`tbd-${i}`}
          className="inline-flex items-center gap-1 px-1.5 py-px rounded text-[11px] font-medium bg-brand-amber-soft text-brand-amber"
        >
          TBD{detail ? `: ${detail}` : ""}
        </span>
      )
    }
  }

  return elements
}

/**
 * Render the detail panel for a slide with sub-items.
 *
 * @param subItems - Array of sub-items to render
 * @param state - Visual state of the parent slide
 * @returns JSX element for the detail panel
 */
function DetailPanel({ subItems, state }: { subItems: OutlineSubItem[]; state: SlideState }): React.ReactElement {
  const whatToSay = subItems.find((s) => s.key === "what_to_say")
  const others = subItems.filter((s) => s.key !== "what_to_say")

  const isActive = state === "active"

  return (
    <div
      className="mt-2 rounded-xl outline-panel-enter"
      style={{
        marginLeft: "36px",
        padding: "16px 20px",
        background: isActive ? "oklch(1 0 0 / 3%)" : "oklch(1 0 0 / 2%)",
        border: "1px solid oklch(1 0 0 / 5%)",
        borderLeft: isActive ? "2px solid oklch(0.75 0.14 185 / 40%)" : "2px solid transparent",
        boxShadow: "inset 0 1px 0 oklch(1 0 0 / 4%)",
        opacity: state === "done" ? 0.85 : 1,
      }}
    >
      {/* what_to_say — no label, largest font, the "voice" of the slide */}
      {whatToSay && (
        <p className="text-[13.5px] text-foreground/90 leading-relaxed">
          {renderValue(whatToSay.value)}
        </p>
      )}

      {/* Other sub-items with icon + label */}
      {others.length > 0 && (
        <div className={whatToSay ? "mt-3 space-y-3" : "space-y-3"}>
          {others.map((item) => {
            const meta = SUB_ITEM_META[item.key as Exclude<SubItemKey, "what_to_say">]
            if (!meta) return null
            const { Icon, label } = meta
            return (
              <div key={item.key} className="flex items-start gap-2.5">
                <Icon
                  className="flex-none w-3.5 h-3.5 mt-[3px] text-brand-teal/40"
                  strokeWidth={1.5}
                />
                <div className="min-w-0 flex-1">
                  <span className="text-[10px] uppercase tracking-[0.08em] text-foreground-secondary/70 font-medium">
                    {label}
                  </span>
                  <p className="text-[12.5px] text-foreground/80 leading-relaxed mt-0.5">
                    {renderValue(item.value)}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/**
 * Render a single timeline node (slide entry).
 *
 * @param props.slide - Parsed slide data
 * @param props.state - Visual state (skeleton / active / done)
 * @param props.index - Position index for stagger animation delay
 * @param props.isLast - Whether this is the last node (no connector line below)
 */
function TimelineNode({ slide, state, index, isLast }: {
  slide: OutlineSlide
  state: SlideState
  index: number
  isLast: boolean
}): React.ReactElement {
  const hasDetail = slide.subItems.length > 0

  // Node circle styles per state.
  const nodeStyles: Record<SlideState, React.CSSProperties> = {
    skeleton: {
      border: "1.5px solid oklch(0.75 0.14 185 / 25%)",
      color: "oklch(0.40 0 0)",
      background: "transparent",
    },
    done: {
      border: "1.5px solid oklch(0.75 0.14 185 / 50%)",
      color: "oklch(0.75 0.14 185)",
      background: "oklch(0.75 0.14 185 / 8%)",
      boxShadow: "0 0 0 3px oklch(0.75 0.14 185 / 6%)",
    },
    active: {
      border: "1.5px solid oklch(0.75 0.14 185 / 70%)",
      color: "oklch(0.75 0.14 185)",
      background: "oklch(0.75 0.14 185 / 15%)",
      boxShadow: "0 0 0 4px oklch(0.75 0.14 185 / 10%)",
    },
  }

  return (
    <div
      className="outline-node-enter relative flex gap-4"
      style={{ "--stagger": `${index * 60}ms` } as React.CSSProperties}
      data-state={state}
      data-slide-num={slide.num}
    >
      {/* Vertical connector line (between nodes) */}
      <div className="flex flex-col items-center flex-none" style={{ width: "24px" }}>
        {/* Node circle */}
        <div
          className={`
            flex-none w-6 h-6 rounded-full flex items-center justify-center
            text-[10px] font-semibold tabular-nums
            transition-all duration-300
            ${state === "active" ? "outline-node-pulse" : ""}
          `}
          style={nodeStyles[state]}
        >
          {slide.num}
        </div>

        {/* Connector line below node */}
        {!isLast && (
          <div
            className="flex-1 w-px mt-2 mb-0"
            style={{
              background: hasDetail
                ? "linear-gradient(to bottom, oklch(0.75 0.14 185 / 25%), oklch(0.75 0.14 185 / 10%))"
                : "oklch(0.75 0.14 185 / 12%)",
              minHeight: "16px",
            }}
          />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pb-6">
        <p className="text-[14px] font-semibold text-foreground leading-snug tracking-[-0.02em]">
          {slide.title}
        </p>
        {slide.message && (
          <p className="text-[12.5px] text-foreground-secondary leading-relaxed mt-0.5">
            {renderColorSwatches(slide.message)}
          </p>
        )}

        {/* Detail panel (Phase B) */}
        {hasDetail && <DetailPanel subItems={slide.subItems} state={state} />}
      </div>
    </div>
  )
}

interface OutlineViewProps {
  content: string | null
}

export function OutlineView({ content }: OutlineViewProps): React.ReactElement {
  const activeRef = useRef<HTMLDivElement>(null)
  const prevActiveNum = useRef<number | null>(null)

  const { slides, states } = useMemo(() => {
    if (!content) return { slides: [], states: [] }
    const parsed = parseOutline(content)
    return { slides: parsed, states: resolveStates(parsed) }
  }, [content])

  // Find the active slide number for auto-scroll.
  const activeIndex = states.indexOf("active")
  const activeNum = activeIndex >= 0 ? slides[activeIndex].num : null

  // Auto-scroll to active slide when it changes.
  useEffect(() => {
    if (activeNum !== null && activeNum !== prevActiveNum.current) {
      prevActiveNum.current = activeNum
      // Defer to allow DOM update + animation start.
      const timer = setTimeout(() => {
        activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
      }, 150)
      return () => clearTimeout(timer)
    }
  }, [activeNum])

  // Empty state.
  if (!content || slides.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-4">
          <FileText className="h-5 w-5 text-foreground-muted/30" />
        </div>
        <p className="text-[13px] text-foreground-muted">
          Outline will appear here when the agent writes it.
        </p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      <div className="max-w-2xl mx-auto">
        {/* Timeline container with flow line animation */}
        <div className="relative outline-timeline-draw">
          {slides.map((slide, i) => (
            <div
              key={slide.num}
              ref={states[i] === "active" ? activeRef : undefined}
            >
              <TimelineNode
                slide={slide}
                state={states[i]}
                index={i}
                isLast={i === slides.length - 1}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
