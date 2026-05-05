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
import { Layers, FileText, Palette, ArrowLeft, Check, Star } from "lucide-react"
import Markdown from "react-markdown"
import type { Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { fetchStyles, fetchStyleHtml, pinStyle, type StyleEntry, type SpecFiles } from "@/services/deckService"
import { OutlineView } from "./OutlineView"
import { StyleSlidePreview } from "@/components/StyleSlidePreview"

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
    return true
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
                relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
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
                  inline-flex items-center justify-center w-4 h-4 rounded-full text-[11px] font-semibold leading-none
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
                <span className={`text-[11px] font-normal ${active ? "text-brand-amber/70" : "text-foreground-muted"}`}>
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
          <code className="text-xs px-1 py-0.5 rounded bg-white/5">{part}</code>
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
export function SpecMarkdownPreview({ content, specName, specKey, onStyleSelect, idToken }: { content: string | null; specName: string; specKey?: string; onStyleSelect?: (name: string) => void; idToken?: string }) {
  // Hooks must be called unconditionally — before any early returns.

  // Art Direction inline gallery state
  type ArtDirectionMode = "gallery" | "preview" | "result"
  const [adMode, setAdMode] = useState<ArtDirectionMode>(content ? "result" : "gallery")
  const [styles, setStyles] = useState<StyleEntry[]>([])
  const [stylesLoading, setStylesLoading] = useState(false)
  const stylesLoadedRef = useRef(false)
  const [preview, setPreview] = useState<{ name: string; html: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const galleryScrollRef = useRef(0)
  const galleryContainerRef = useRef<HTMLDivElement>(null)
  const [allStylesOpen, setAllStylesOpen] = useState(true)

  // Pin toggle — optimistic UI with API persistence
  // Preserve scroll position across re-renders caused by section layout changes
  const handlePinToggle = useCallback((name: string) => {
    const scrollTop = galleryContainerRef.current?.scrollTop ?? 0
    setStyles(prev => {
      const style = prev.find(s => s.name === name)
      const newPinned = !style?.pinned
      if (idToken) pinStyle(name, newPinned, idToken)
      return prev.map(s => s.name === name ? { ...s, pinned: newPinned } : s)
    })
    requestAnimationFrame(() => {
      if (galleryContainerRef.current) galleryContainerRef.current.scrollTop = scrollTop
    })
  }, [idToken])

  // Sync mode when content appears externally (e.g. polling updates art-direction)
  const userRequestedGallery = useRef(false)
  useEffect(() => {
    if (specKey !== "artDirection") return
    if (content && adMode === "gallery" && !preview && !userRequestedGallery.current) setAdMode("result")
    if (!content && adMode === "result") setAdMode("gallery")
  }, [content, specKey, adMode, preview])

  // Fetch styles when gallery is shown
  useEffect(() => {
    if (specKey !== "artDirection" || adMode !== "gallery" || stylesLoadedRef.current || !idToken) return
    let cancelled = false
    setStylesLoading(true)
    fetchStyles(idToken).then((s) => {
      if (cancelled) return
      stylesLoadedRef.current = true
      setStyles(s)
      setStylesLoading(false)
    })
    return () => { cancelled = true }
  }, [specKey, adMode, idToken])

  // Esc key handling for art direction states
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (specKey !== "artDirection") return
    if (e.key === "Escape") {
      if (adMode === "preview") {
        setPreview(null)
        setAdMode("gallery")
      } else if (adMode === "gallery" && content) {
        setAdMode("result")
      }
    }
  }, [specKey, adMode, content])

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [handleKeyDown])

  // Outline tab: show waiting animation when no content, timeline when content exists.
  if (specKey === "outline" && !content) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        <OutlineWaiting />
      </div>
    )
  }
  if (specKey === "outline") {
    return <div className="content-enter flex-1"><OutlineView content={content} /></div>
  }

  // Art Direction: 3-state inline view
  if (specKey === "artDirection") {
    // Waiting state (no content, not browsing styles)
    if (!content && adMode === "result") {
      return (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
          <ArtDirectionWaiting />
        </div>
      )
    }

    // GALLERY state
    if (adMode === "gallery") {
      const handleCardClick = async (name: string) => {
        if (galleryContainerRef.current) galleryScrollRef.current = galleryContainerRef.current.scrollTop
        userRequestedGallery.current = false
        setPreviewLoading(true)
        setPreview({ name, html: "" })
        setAdMode("preview")
        if (idToken) {
          const html = await fetchStyleHtml(name, idToken)
          setPreview({ name, html })
        }
        setPreviewLoading(false)
      }

      const pinnedStyles = styles.filter(s => s.pinned)
      const hasPins = pinnedStyles.length > 0
      const unpinnedStyles = styles.filter(s => !s.pinned)

      return (
        <div ref={galleryContainerRef} className="flex-1 overflow-y-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/[0.06]">
            <div>
              <h2 className="text-[15px] font-semibold">Choose a Style</h2>
              <p className="text-xs text-foreground-muted mt-0.5">Click to preview · ★ to pin favorites</p>
            </div>
            {content && (
              <button
                onClick={() => { userRequestedGallery.current = false; setAdMode("result") }}
                className="inline-flex items-center gap-1.5 text-xs text-foreground-muted hover:text-foreground px-3 py-1.5 rounded-lg border border-white/[0.06] hover:bg-white/[0.06] transition-colors"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Back to Art Direction
              </button>
            )}
          </div>
          {/* Grid */}
          <div className="p-6">
            {stylesLoading ? (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="aspect-[16/10] rounded-xl bg-white/[0.03] animate-pulse" />
                ))}
              </div>
            ) : hasPins ? (
              /* Sectioned layout: Pinned + All Styles collapsible */
              <div className="flex flex-col gap-6">
                {/* Pinned section */}
                <div>
                  <div className="flex items-center gap-1.5 mb-3">
                    <Star className="h-3.5 w-3.5 text-brand-teal" fill="currentColor" />
                    <h3 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">Pinned</h3>
                  </div>
                  <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                    {pinnedStyles.map((style, i) => (
                      <StyleCard key={style.name} style={style} index={i} onClick={handleCardClick} onPin={handlePinToggle} />
                    ))}
                  </div>
                </div>
                {/* All Styles collapsible */}
                <div>
                  <button
                    onClick={() => setAllStylesOpen(prev => !prev)}
                    className="flex items-center gap-1.5 mb-3 text-xs font-semibold text-foreground-muted uppercase tracking-wider hover:text-foreground transition-colors"
                    aria-expanded={allStylesOpen}
                  >
                    <span className="transition-transform duration-200" style={{ transform: allStylesOpen ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
                    All Styles ({unpinnedStyles.length})
                  </button>
                  {allStylesOpen && (
                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                      {unpinnedStyles.map((style, i) => (
                        <StyleCard key={style.name} style={style} index={i} onClick={handleCardClick} onPin={handlePinToggle} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              /* Flat layout: no pins */
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {styles.map((style, i) => (
                  <StyleCard key={style.name} style={style} index={i} onClick={handleCardClick} onPin={handlePinToggle} />
                ))}
              </div>
            )}
          </div>
        </div>
      )
    }

    // PREVIEW state
    if (adMode === "preview" && preview) {
      const previewStyle = styles.find(s => s.name === preview.name)
      const previewPinned = previewStyle?.pinned ?? false

      const handleSelect = () => {
        if (onStyleSelect) onStyleSelect(preview.name)
        if (content) setAdMode("result")
        else { setPreview(null); setAdMode("gallery") }
      }

      return (
        <div className="flex-1 overflow-y-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/[0.06]">
            <div className="flex items-center gap-3">
              <button
                onClick={() => { setPreview(null); setAdMode("gallery"); }}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-white/[0.06] transition-colors"
                aria-label="Back to styles"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <div className="flex items-center gap-2">
                <h2 className="text-[15px] font-semibold">{preview.name}</h2>
                <button
                  onClick={() => handlePinToggle(preview.name)}
                  className={`p-1 rounded transition-colors ${previewPinned ? "text-brand-teal" : "text-foreground-muted hover:text-foreground"}`}
                  aria-label={previewPinned ? `Unpin ${preview.name}` : `Pin ${preview.name}`}
                >
                  <Star className="h-3.5 w-3.5" fill={previewPinned ? "currentColor" : "none"} />
                </button>
              </div>
              <p className="text-xs text-foreground-muted">Preview all slides — select to apply</p>
            </div>
            <button
              onClick={handleSelect}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-teal text-primary-foreground hover:bg-brand-teal/90 transition-colors"
            >
              <Check className="h-3.5 w-3.5" />
              Select
            </button>
          </div>
          {/* Preview content */}
          <div className="p-6">
            <StyleSlidePreview html={preview.html} loading={previewLoading} />
          </div>
        </div>
      )
    }

    // RESULT state (default when content exists)
    return (
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {onStyleSelect && (
          <div className="flex justify-end px-4 py-2">
            <button
              onClick={() => { userRequestedGallery.current = true; setAdMode("gallery") }}
              className="inline-flex items-center gap-1.5 text-xs text-foreground-muted hover:text-foreground px-3 py-1.5 rounded-lg border border-white/[0.06] hover:bg-white/[0.06] transition-colors"
            >
              <Palette className="h-3.5 w-3.5" />
              Change Style
            </button>
          </div>
        )}
        <StyleSlidePreview html={content!} loading={false} />
      </div>
    )
  }

  if (!content) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        {specKey === "brief" && <BriefWaiting />}
        {specKey === "outline" && <OutlineWaiting />}
        {(!specKey || !["brief", "outline", "artDirection"].includes(specKey)) && (
          <>
            <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-4 text-foreground-muted/40">
              <FileText className="h-5 w-5" />
            </div>
            <p className="text-sm text-foreground-muted">{specName} will appear here.</p>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="content-enter flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      <article className="prose prose-invert prose-sm max-w-3xl mx-auto spec-prose">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={specComponents as Components}
        >
          {content}
        </Markdown>
      </article>
    </div>
  )
}

/* ── Inline style components ── */

/** Individual style card with iframe cover preview. */
function StyleCard({ style, index, onClick, onPin }: { style: StyleEntry; index: number; onClick: (name: string) => void; onPin?: (name: string) => void }) {
  const iframeWidth = 1920
  const iframeHeight = 1080
  const cardRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.2)
  const [bouncing, setBouncing] = useState(false)

  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setScale(entry.contentRect.width / iframeWidth)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const handlePin = (e: React.MouseEvent) => {
    e.stopPropagation()
    setBouncing(true)
    setTimeout(() => setBouncing(false), 300)
    onPin?.(style.name)
  }

  return (
    <div
      ref={cardRef}
      role="button"
      tabIndex={0}
      onClick={() => onClick(style.name)}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(style.name) } }}
      className="group text-left rounded-xl border border-white/[0.06] overflow-hidden transition-all duration-300 hover:border-brand-teal/30 hover:shadow-[0_0_24px_oklch(0.75_0.14_185/10%)] focus:outline-none focus:ring-2 focus:ring-brand-teal/40 animate-[card-in_0.5s_ease_both] cursor-pointer"
      style={{ animationDelay: `${index * 60}ms` }}
      aria-label={`Preview ${style.name} style`}
    >
      <div className="relative overflow-hidden bg-black/20" style={{ height: iframeHeight * scale }}>
        {style.coverHtml ? (
          <iframe
            srcDoc={style.coverHtml}
            sandbox=""
            title={style.name}
            style={{
              width: iframeWidth,
              height: iframeHeight,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
              border: "none",
              pointerEvents: "none",
            }}
            tabIndex={-1}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-foreground-muted text-xs">
            No preview
          </div>
        )}
        <div className="absolute inset-0 bg-brand-teal/0 group-hover:bg-brand-teal/5 transition-colors duration-300" />
        {/* Pin button */}
        {onPin && (
          <button
            onClick={handlePin}
            className={`absolute top-2 right-2 w-7 h-7 rounded-lg flex items-center justify-center transition-all duration-150 ${
              style.pinned
                ? "opacity-100 bg-black/40 text-brand-teal"
                : "opacity-0 group-hover:opacity-100 bg-black/40 text-white/30 hover:text-white/60"
            }`}
            style={{ transform: bouncing ? "scale(1.3)" : "scale(1)", transition: "transform 300ms ease-out" }}
            aria-label={style.pinned ? `Unpin ${style.name}` : `Pin ${style.name}`}
          >
            <Star className="h-3.5 w-3.5" fill={style.pinned ? "currentColor" : "none"} />
          </button>
        )}
      </div>
      <div className="px-3 py-2.5 border-t border-white/[0.04]">
        <div className="flex items-center gap-1.5">
          <p className="text-sm font-medium text-foreground group-hover:text-brand-teal transition-colors truncate">{style.name}</p>
          {style.source === "user" && (
            <span className="flex-none text-[11px] px-1.5 py-0.5 rounded-full bg-brand-teal/10 text-brand-teal font-medium">Custom</span>
          )}
        </div>
        {style.description && (
          <p className="text-xs text-foreground-muted mt-0.5 line-clamp-1">{style.description}</p>
        )}
      </div>
    </div>
  )
}

/** Full style preview rendered via scaled iframe. */
export /* ── Spec waiting animations ── */

const WAIT_COLORS = [
  { css: "var(--wait-teal)", raw: "oklch(0.75 0.14 185)" },
  { css: "var(--wait-amber)", raw: "oklch(0.82 0.16 75)" },
  { css: "var(--wait-magenta)", raw: "oklch(0.70 0.18 330)" },
  { css: "var(--wait-green)", raw: "oklch(0.78 0.15 145)" },
]

/** Brief: page being written with colorful lines and glowing cursor. */
function BriefWaiting() {
  const lines = [
    { w: 85, color: 0 }, { w: 65, color: 1 }, { w: 90, color: 2 },
    { w: 50, color: 3 }, { w: 75, color: 0 }, { w: 60, color: 1 },
  ]
  return (
    <div className="brief-waiting flex flex-col items-center gap-6">
      <div
        className="w-64 rounded-2xl p-6 flex flex-col gap-2.5"
        style={{
          background: "oklch(0.13 0.005 260)",
          border: "1px solid oklch(1 0 0 / 6%)",
          boxShadow: "0 0 40px oklch(0.75 0.14 185 / 6%), 0 8px 32px oklch(0 0 0 / 40%)",
        }}
      >
        {lines.map((l, i) => (
          <div
            key={i}
            className="brief-line-el h-[5px] rounded-full"
            style={{
              width: `${l.w}%`,
              background: WAIT_COLORS[l.color].raw,
              opacity: 0.5,
              animation: `brief-line 3s ease-in-out ${i * 0.35}s infinite`,
            }}
          />
        ))}
        <div className="flex items-center mt-1">
          <div
            className="brief-cursor-glow w-[3px] h-5 rounded-full"
            style={{
              background: WAIT_COLORS[0].raw,
              boxShadow: `0 0 12px ${WAIT_COLORS[0].raw}`,
              animation: "brief-cursor 0.8s step-end infinite",
              transition: "box-shadow 0.3s ease",
            }}
          />
        </div>
      </div>
      <p className="text-sm text-foreground-muted">Drafting the brief…</p>
    </div>
  )
}

/** Outline: tree growing with trunk, branches, and colorful nodes. */
function OutlineWaiting() {
  const nodes = [
    { level: 0, color: 0 }, { level: 1, color: 2 }, { level: 1, color: 3 },
    { level: 0, color: 1 }, { level: 1, color: 0 }, { level: 1, color: 2 },
    { level: 0, color: 3 },
  ]
  return (
    <div className="outline-waiting flex flex-col items-center gap-6">
      <div className="relative w-56" style={{ height: 220 }}>
        {/* Trunk line */}
        <div
          className="absolute left-[14px] top-0 w-[2px] rounded-full"
          style={{
            background: `linear-gradient(to bottom, ${WAIT_COLORS[0].raw}, ${WAIT_COLORS[1].raw})`,
            animation: "outline-trunk-grow 1.2s ease-out both",
            height: "100%",
          }}
        />
        {/* Nodes */}
        {nodes.map((n, i) => {
          const c = WAIT_COLORS[n.color]
          const y = i * 30
          const isParent = n.level === 0
          const size = isParent ? 12 : 9
          const left = isParent ? 9 : 28
          return (
            <div key={i} className="absolute flex items-center" style={{ top: y, left }}>
              {/* Branch line for children */}
              {!isParent && (
                <div
                  className="absolute h-[1.5px] rounded-full"
                  style={{
                    left: -14,
                    width: 16,
                    background: c.raw,
                    opacity: 0.4,
                    animation: `outline-wait-branch 0.4s ease-out ${0.8 + i * 0.15}s both`,
                  }}
                />
              )}
              {/* Node dot */}
              <div
                className="outline-wait-node-el rounded-full"
                style={{
                  width: size,
                  height: size,
                  background: c.raw,
                  "--node-color": c.raw,
                  animation: `outline-wait-node 0.5s cubic-bezier(0.22, 1, 0.36, 1) ${0.6 + i * 0.15}s both`,
                } as React.CSSProperties}
              />
              <div
                className="outline-wait-glow-el absolute rounded-full"
                style={{
                  width: size,
                  height: size,
                  "--node-color": c.raw,
                  animation: `outline-wait-glow 2.5s ease-in-out ${i * 0.3}s infinite`,
                } as React.CSSProperties}
              />
              {/* Label line */}
              <div
                className="ml-3 h-[4px] rounded-full"
                style={{
                  width: isParent ? 80 : 56,
                  background: c.raw,
                  opacity: 0.2,
                  animation: `brief-line 3.6s ease-in-out ${0.8 + i * 0.2}s infinite`,
                }}
              />
            </div>
          )
        })}
      </div>
      <p className="text-sm text-foreground-muted">Structuring the outline…</p>
    </div>
  )
}

/** Art Direction: orbiting color dots with glow trails and pointer interaction. */
function ArtDirectionWaiting() {
  const containerRef = useRef<HTMLDivElement>(null)

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width - 0.5) * 12
    const y = ((e.clientY - rect.top) / rect.height - 0.5) * 12
    el.style.setProperty("--px", `${x}px`)
    el.style.setProperty("--py", `${y}px`)
  }, [])

  const handleMouseLeave = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    el.style.setProperty("--px", "0px")
    el.style.setProperty("--py", "0px")
  }, [])

  return (
    <div className="art-waiting flex flex-col items-center gap-6">
      <div
        ref={containerRef}
        className="relative w-24 h-24"
        style={{
          "--px": "0px",
          "--py": "0px",
          animation: "art-hue 8s linear infinite",
          transform: "translate(var(--px), var(--py))",
          transition: "transform 0.3s ease-out",
        } as React.CSSProperties}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {WAIT_COLORS.map((c, i) => (
          <div key={i} className="absolute inset-0 flex items-center justify-center" style={{
            animation: `art-orbit 3s ease-in-out ${i * 0.75}s infinite`,
          }}>
            <div className="art-dot w-4 h-4 rounded-full" style={{
              background: c.raw,
              boxShadow: `0 0 16px ${c.raw}, 0 0 32px ${c.raw}`,
              transition: "animation-duration 0.3s",
            }} />
          </div>
        ))}
        {/* Center pulse */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-3 h-3 rounded-full" style={{
            background: "oklch(1 0 0 / 25%)",
            boxShadow: `0 0 12px ${WAIT_COLORS[0].raw}`,
            animation: "art-center-pulse 2.5s ease-in-out infinite",
          }} />
        </div>
      </div>
      <p className="text-sm text-foreground-muted">Composing art direction…</p>
    </div>
  )
}
