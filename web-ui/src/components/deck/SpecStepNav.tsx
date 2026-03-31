// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SpecStepNav — Kiro-inspired step navigation for spec files.
 *
 * Displays a horizontal step bar: 1 Brief → 2 Outline → 3 Art Direction → ◆ Slides.
 * Spec tabs are grayed out when content is null, and auto-focus when content appears.
 * When a spec tab is active, renders markdown content with prose styling.
 *
 * @param props.specs - Spec file contents (null = not yet created)
 * @param props.activeTab - Currently active tab key
 * @param props.onTabChange - Callback when user clicks a tab
 * @param props.slideCount - Number of slides (shown as badge on Slides tab)
 */

"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Layers, FileText } from "lucide-react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { SpecFiles } from "@/services/deckService"
import { OutlineView } from "./OutlineView"

/** Tab key union type for spec viewer navigation. */
export type SpecTab = "brief" | "outline" | "artDirection" | "slides"

/** Step definition for the navigation bar. */
interface StepDef {
  key: SpecTab
  label: string
  step?: number
}

const STEPS: StepDef[] = [
  { key: "brief", label: "Brief", step: 1 },
  { key: "outline", label: "Outline", step: 2 },
  { key: "artDirection", label: "Art Direction", step: 3 },
  { key: "slides", label: "Slides" },
]

interface SpecStepNavProps {
  specs: SpecFiles | null | undefined
  activeTab: SpecTab
  onTabChange: (tab: SpecTab) => void
  slideCount: number
}

export function SpecStepNav({ specs, activeTab, onTabChange, slideCount }: SpecStepNavProps) {
  /**
   * Check whether a spec tab has content.
   *
   * @param key - The spec tab key
   * @returns true if the spec file exists and has content
   */
  function hasContent(key: SpecTab): boolean {
    if (key === "slides") return true
    return specs?.[key] != null
  }

  return (
    <nav className="flex items-center gap-1 px-5 py-2 border-b border-border/40" role="tablist" aria-label="Spec phases">
      {STEPS.map((s, i) => {
        const isSlides = s.key === "slides"
        const active = activeTab === s.key
        const enabled = hasContent(s.key)

        return (
          <div key={s.key} className="flex items-center">
            {/* Connector line between steps */}
            {i > 0 && (
              <div className={`w-4 h-px mx-1 transition-colors duration-300 ${
                enabled && hasContent(STEPS[i - 1].key)
                  ? "bg-border-hover"
                  : "bg-border/30"
              }`} />
            )}

            <button
              role="tab"
              aria-selected={active}
              aria-disabled={!enabled}
              disabled={!enabled}
              onClick={() => onTabChange(s.key)}
              className={`
                relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium
                transition-all duration-300 select-none
                ${active
                  ? isSlides
                    ? "bg-brand-amber-soft text-brand-amber"
                    : "bg-brand-teal-soft text-brand-teal"
                  : enabled
                    ? "text-foreground-secondary hover:text-foreground hover:bg-background-hover"
                    : "text-foreground-muted/40 cursor-not-allowed"
                }
              `}
            >
              {/* Step number badge or Slides icon */}
              {isSlides ? (
                <Layers className={`h-3.5 w-3.5 ${active ? "text-brand-amber" : ""}`} />
              ) : (
                <span className={`
                  inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-semibold leading-none
                  transition-all duration-300
                  ${active
                    ? "bg-brand-teal text-primary-foreground"
                    : enabled
                      ? "bg-foreground-muted/15 text-foreground-secondary"
                      : "bg-foreground-muted/8 text-foreground-muted/30"
                  }
                `}>
                  {s.step}
                </span>
              )}

              {s.label}

              {/* Slide count badge */}
              {isSlides && slideCount > 0 && (
                <span className={`text-[10px] font-normal ${active ? "text-brand-amber/70" : "text-foreground-muted"}`}>
                  · {slideCount}
                </span>
              )}

              {/* Active indicator dot */}
              {active && (
                <span className={`absolute -bottom-2.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full ${
                  isSlides ? "bg-brand-amber" : "bg-brand-teal"
                }`} />
              )}
            </button>
          </div>
        )
      })}
    </nav>
  )
}

/** Regex matching HEX color codes in text. */
const HEX_RE = /(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))\b/g

/**
 * Render inline color swatches next to HEX codes in text.
 *
 * @param text - Raw text that may contain HEX color codes
 * @returns Array of string and JSX elements with color swatches
 */
export function renderColorSwatches(text: string): (string | React.ReactElement)[] {
  const parts = text.split(HEX_RE)
  return parts.map((part, i) => {
    if (/^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test(part)) {
      return (
        <span key={i} className="inline-flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full border border-white/20 flex-none"
            style={{ backgroundColor: part }}
            aria-label={`Color ${part}`}
          />
          <code className="text-[12px] px-1 py-0.5 rounded bg-white/5">{part}</code>
        </span>
      )
    }
    return part
  })
}

/**
 * Shared markdown components for spec rendering — adds HEX color swatches.
 */
const specComponents = {
  p: ({ children, ...props }: React.ComponentProps<"p">) => (
    <p {...props}>
      {typeof children === "string" ? renderColorSwatches(children) : children}
    </p>
  ),
  li: ({ children, ...props }: React.ComponentProps<"li">) => (
    <li {...props}>
      {typeof children === "string" ? renderColorSwatches(children) : children}
    </li>
  ),
  code: ({ children, className, ...props }: React.ComponentProps<"code">) => {
    if (!className && typeof children === "string" && /^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test(children.trim())) {
      const color = children.trim()
      return (
        <span className="inline-flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full border border-white/20 flex-none"
            style={{ backgroundColor: color }}
            aria-label={`Color ${color}`}
          />
          <code className={className} {...props}>{children}</code>
        </span>
      )
    }
    return <code className={className} {...props}>{children}</code>
  },
}

/**
 * SpecMarkdownPreview — Renders spec markdown content with editorial styling.
 * Outline uses the dedicated OutlineView timeline component.
 * Brief uses react-markdown with HEX color swatches.
 * Art Direction renders HTML via sandboxed iframe.
 *
 * @param props.content - Markdown or HTML string to render
 * @param props.specName - Name of the spec (for empty state)
 * @param props.specKey - Which spec tab ("brief" | "outline" | "artDirection")
 */
export function SpecMarkdownPreview({ content, specName, specKey }: { content: string | null; specName: string; specKey?: string }) {
  // Outline tab uses the dedicated timeline renderer.
  if (specKey === "outline") {
    return <OutlineView content={content} />
  }

  if (!content) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        {specKey === "brief" && <BriefWaiting />}
        {specKey === "outline" && <OutlineWaiting />}
        {specKey === "artDirection" && <ArtDirectionWaiting />}
        {(!specKey || !["brief", "outline", "artDirection"].includes(specKey)) && (
          <>
            <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-4 text-foreground-muted/40">
              <FileText className="h-5 w-5" />
            </div>
            <p className="text-[13px] text-foreground-muted">{specName} will appear here.</p>
          </>
        )}
      </div>
    )
  }

  // Art Direction tab renders HTML via sandboxed iframe.
  // Style HTMLs use fixed 1920px-wide body. We render the iframe at 1920px
  // and use CSS transform to scale it down to fit the container.
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (specKey === "artDirection") {
    const ratio = containerWidth > 0 ? containerWidth / 1920 : 1
    return (
      <div ref={containerRef} className="flex-1 overflow-y-auto overflow-x-hidden">
        <div style={{ width: containerWidth, height: 1080 * ratio * 10, overflow: "hidden" }}>
          <iframe
            srcDoc={content}
            sandbox="allow-same-origin"
            title="Art Direction"
            style={{
              width: 1920,
              height: 10800,
              border: "none",
              transformOrigin: "top left",
              transform: `scale(${ratio})`,
            }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      <article className="prose prose-invert prose-sm max-w-3xl mx-auto spec-prose">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={specComponents}
        >
          {content}
        </Markdown>
      </article>
    </div>
  )
}

/* ── Spec waiting animations ── */

/** Brief: typewriter lines appearing one by one with a blinking cursor. */
function BriefWaiting() {
  const widths = [85, 70, 90, 55, 75]
  return (
    <div className="flex flex-col items-center gap-5">
      <div className="w-40 flex flex-col gap-[6px]">
        {widths.map((w, i) => (
          <div key={i} className="h-[3px] rounded-full bg-brand-teal/30" style={{
            width: `${w}%`,
            animation: `brief-line 3s ease-in-out ${i * 0.4}s infinite`,
          }} />
        ))}
        <div className="w-[2px] h-3 bg-brand-teal/70 mt-1" style={{
          animation: "brief-cursor 0.8s step-end infinite",
        }} />
      </div>
      <p className="text-[13px] text-foreground-muted">Drafting the brief…</p>
    </div>
  )
}

/** Outline: blocks stacking and fading in a staggered loop. */
function OutlineWaiting() {
  const blocks = [
    { w: "100%", indent: 0 },
    { w: "70%", indent: 12 },
    { w: "60%", indent: 12 },
    { w: "100%", indent: 0 },
    { w: "80%", indent: 12 },
    { w: "50%", indent: 12 },
  ]
  return (
    <div className="flex flex-col items-center gap-5">
      <div className="w-36 flex flex-col gap-[5px]">
        {blocks.map((b, i) => (
          <div key={i} className="flex items-center gap-1.5" style={{ paddingLeft: b.indent }}>
            {b.indent === 0 && <div className="w-1.5 h-1.5 rounded-full bg-brand-amber/50 shrink-0" />}
            {b.indent > 0 && <div className="w-1 h-1 rounded-full bg-foreground-muted/30 shrink-0" />}
            <div className="h-[3px] rounded-full bg-foreground-muted/25" style={{
              width: b.w,
              animation: `outline-block 3.6s ease-in-out ${i * 0.3}s infinite`,
            }} />
          </div>
        ))}
      </div>
      <p className="text-[13px] text-foreground-muted">Structuring the outline…</p>
    </div>
  )
}

/** Art Direction: orbiting color dots with hue rotation. */
function ArtDirectionWaiting() {
  const colors = [
    "oklch(0.75 0.14 185)",  // teal
    "oklch(0.82 0.16 75)",   // amber
    "oklch(0.70 0.18 330)",  // magenta
    "oklch(0.78 0.15 145)",  // green
  ]
  return (
    <div className="flex flex-col items-center gap-5">
      <div className="relative w-14 h-14" style={{ animation: "art-hue 8s linear infinite" }}>
        {colors.map((c, i) => (
          <div key={i} className="absolute inset-0 flex items-center justify-center" style={{
            animation: `art-orbit 3s ease-in-out ${i * 0.75}s infinite`,
          }}>
            <div className="w-3 h-3 rounded-full" style={{
              background: c,
              boxShadow: `0 0 12px ${c}`,
            }} />
          </div>
        ))}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-2 h-2 rounded-full bg-white/20" />
        </div>
      </div>
      <p className="text-[13px] text-foreground-muted">Composing art direction…</p>
    </div>
  )
}
