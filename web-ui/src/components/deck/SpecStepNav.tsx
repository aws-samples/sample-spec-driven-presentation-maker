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
import { Layers, FileText, Palette, ArrowLeft, Check } from "lucide-react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { fetchStyles, fetchStyleHtml, type StyleEntry, type SpecFiles } from "@/services/deckService"
import { listUserStyles, getUserStyle } from "@/services/resourcesService"
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
export function SpecMarkdownPreview({ content, specName, specKey, onStyleSelect, idToken }: { content: string | null; specName: string; specKey?: string; onStyleSelect?: (name: string) => void; idToken?: string }) {
  // Hooks must be called unconditionally — before any early returns.
  const [containerWidth, setContainerWidth] = useState(0)

  // Art Direction inline gallery state
  type ArtDirectionMode = "gallery" | "preview" | "result"
  const [adMode, setAdMode] = useState<ArtDirectionMode>(content ? "result" : "gallery")
  const [styles, setStyles] = useState<StyleEntry[]>([])
  const [galleryTab, setGalleryTab] = useState<"examples" | "user">("examples")
  const [stylesLoading, setStylesLoading] = useState(false)
  const stylesLoadedRef = useRef(false)
  const [preview, setPreview] = useState<{ name: string; scope: "examples" | "user"; html: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const galleryScrollRef = useRef(0)
  const galleryContainerRef = useRef<HTMLDivElement>(null)

  // Sync mode when content appears externally (e.g. polling updates art-direction)
  const userRequestedGallery = useRef(false)
  useEffect(() => {
    if (specKey !== "artDirection") return
    if (content && adMode === "gallery" && !preview && !userRequestedGallery.current) setAdMode("result")
    if (!content && adMode === "result") setAdMode("gallery")
  }, [content, specKey, adMode, preview])

  // Fetch styles when gallery is shown (examples + user styles merged)
  useEffect(() => {
    if (specKey !== "artDirection" || adMode !== "gallery" || stylesLoadedRef.current || !idToken) return
    let cancelled = false
    setStylesLoading(true)
    Promise.all([fetchStyles(idToken), listUserStyles(idToken)]).then(([examples, user]) => {
      if (cancelled) return
      stylesLoadedRef.current = true
      const merged: StyleEntry[] = [
        ...examples.map(s => ({ ...s, scope: "examples" as const })),
        ...user.map(s => ({ name: s.name, description: s.description, coverHtml: s.coverHtml || "", scope: "user" as const })),
      ]
      setStyles(merged)
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

  // Art Direction result iframe: callback ref for ResizeObserver (handles mount/unmount across states)
  const resultRoRef = useRef<ResizeObserver | null>(null)
  const resultMeasuredRef = useCallback((node: HTMLDivElement | null) => {
    if (resultRoRef.current) {
      resultRoRef.current.disconnect()
      resultRoRef.current = null
    }
    if (node) {
      const w = node.getBoundingClientRect().width
      if (w > 0) setContainerWidth(w)
      resultRoRef.current = new ResizeObserver(([entry]) => {
        setContainerWidth(entry.contentRect.width)
      })
      resultRoRef.current.observe(node)
    }
  }, [])

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
      const handleCardClick = async (name: string, scope: "examples" | "user") => {
        if (galleryContainerRef.current) galleryScrollRef.current = galleryContainerRef.current.scrollTop
        userRequestedGallery.current = false
        setPreviewLoading(true)
        setPreview({ name, scope, html: "" })
        setAdMode("preview")
        if (idToken) {
          const html = scope === "user"
            ? await getUserStyle(name, idToken)
            : await fetchStyleHtml(name, idToken)
          setPreview({ name, scope, html })
        }
        setPreviewLoading(false)
      }

      const visibleStyles = styles.filter(s => (s.scope || "examples") === galleryTab)
      const userCount = styles.filter(s => s.scope === "user").length
      const exampleCount = styles.filter(s => (s.scope || "examples") === "examples").length

      return (
        <div ref={galleryContainerRef} className="flex-1 overflow-y-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/[0.06]">
            <div>
              <h2 className="text-sm font-semibold">Choose a Style</h2>
              <p className="text-xs text-foreground-muted mt-0.5">Click a style to preview</p>
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
          {/* Tabs */}
          <div className="flex gap-1 px-6 pt-3 border-b border-white/[0.04]">
            <button
              onClick={() => setGalleryTab("examples")}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-md transition-colors ${
                galleryTab === "examples" ? "text-foreground bg-white/[0.06]" : "text-foreground-muted hover:text-foreground-secondary"
              }`}
            >
              Examples{exampleCount > 0 && <span className="text-[10px] text-foreground-muted ml-1">· {exampleCount}</span>}
            </button>
            <button
              onClick={() => setGalleryTab("user")}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-md transition-colors ${
                galleryTab === "user" ? "text-foreground bg-white/[0.06]" : "text-foreground-muted hover:text-foreground-secondary"
              }`}
            >
              My{userCount > 0 && <span className="text-[10px] text-foreground-muted ml-1">· {userCount}</span>}
            </button>
          </div>
          {/* Grid */}
          <div className="p-6">
            {stylesLoading ? (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="aspect-[16/10] rounded-xl bg-white/[0.03] animate-pulse" />
                ))}
              </div>
            ) : visibleStyles.length === 0 ? (
              <div className="text-center py-20 text-xs text-foreground-muted">
                {galleryTab === "user"
                  ? "No personal styles yet. Use Customize → New Style to create one."
                  : "No example styles available."}
              </div>
            ) : (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {visibleStyles.map((style, i) => (
                  <StyleCard
                    key={`${style.scope}:${style.name}`}
                    style={style}
                    index={i}
                    onClick={(n) => handleCardClick(n, style.scope || "examples")}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )
    }

    // PREVIEW state
    if (adMode === "preview" && preview) {
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
              <div>
                <h2 className="text-sm font-semibold">{preview.name}</h2>
                <p className="text-xs text-foreground-muted mt-0.5">Preview all slides — select to apply</p>
              </div>
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
            <StylePreviewInline html={preview.html} loading={previewLoading} />
          </div>
        </div>
      )
    }

    // RESULT state (default when content exists)
    const ratio = containerWidth > 0 ? containerWidth / 1920 : 1
    return (
      <div ref={resultMeasuredRef} className="flex-1 overflow-y-auto overflow-x-hidden">
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
        <div style={{ width: containerWidth, height: 1080 * ratio * 10, overflow: "hidden" }}>
          <iframe
            srcDoc={content!}
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
            <p className="text-[13px] text-foreground-muted">{specName} will appear here.</p>
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
          components={specComponents}
        >
          {content}
        </Markdown>
      </article>
    </div>
  )
}

/* ── Inline style components ── */

/** Individual style card with iframe cover preview. */
function StyleCard({ style, index, onClick }: { style: StyleEntry; index: number; onClick: (name: string) => void }) {
  const iframeWidth = 1920
  const iframeHeight = 1080
  const cardRef = useRef<HTMLButtonElement>(null)
  const [scale, setScale] = useState(0.2)

  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setScale(entry.contentRect.width / iframeWidth)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <button
      ref={cardRef}
      onClick={() => onClick(style.name)}
      className="group text-left rounded-xl border border-white/[0.06] overflow-hidden transition-all duration-300 hover:border-brand-teal/30 hover:shadow-[0_0_24px_oklch(0.75_0.14_185/10%)] focus:outline-none focus:ring-2 focus:ring-brand-teal/40 animate-[card-in_0.5s_ease_both]"
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
      </div>
      <div className="px-3 py-2.5 border-t border-white/[0.04]">
        <p className="text-[13px] font-medium text-foreground group-hover:text-brand-teal transition-colors">{style.name}</p>
        {style.description && (
          <p className="text-[11px] text-foreground-muted mt-0.5 line-clamp-1">{style.description}</p>
        )}
      </div>
    </button>
  )
}

/** Full style preview rendered via scaled iframe. */
function StylePreviewInline({ html, loading }: { html: string; loading: boolean }) {
  const [containerWidth, setContainerWidth] = useState(0)

  // Callback ref to handle DOM element changes (e.g. after loading→content transition)
  const roRef = useRef<ResizeObserver | null>(null)
  const measuredRef = useCallback((node: HTMLDivElement | null) => {
    if (roRef.current) {
      roRef.current.disconnect()
      roRef.current = null
    }
    if (node) {
      const w = node.getBoundingClientRect().width
      if (w > 0) setContainerWidth(w)
      roRef.current = new ResizeObserver(([entry]) => {
        setContainerWidth(entry.contentRect.width)
      })
      roRef.current.observe(node)
    }
  }, [])

  if (loading || !html) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
      </div>
    )
  }

  const ratio = containerWidth > 0 ? containerWidth / 1920 : 0
  const slideCount = (html.match(/class="slide"/g) || []).length || 5

  return (
    <div ref={measuredRef} className="w-full overflow-x-hidden">
      <div style={{ width: "100%", height: ratio > 0 ? 1080 * ratio * slideCount : 400, overflow: "hidden" }}>
        {ratio > 0 ? (
          <iframe
            srcDoc={html}
            sandbox="allow-same-origin"
            title="Style Preview"
            style={{
              width: 1920,
              height: 1080 * slideCount,
              border: "none",
              transformOrigin: "top left",
              transform: `scale(${ratio})`,
            }}
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="w-6 h-6 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Spec waiting animations ── */

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
      <p className="text-[13px] text-foreground-muted">Drafting the brief…</p>
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
      <p className="text-[13px] text-foreground-muted">Structuring the outline…</p>
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
      <p className="text-[13px] text-foreground-muted">Composing art direction…</p>
    </div>
  )
}
