// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlideCarousel — Vertical scroll layout for slide PNG previews with spec step navigation.
 * Shows all slides stacked vertically with PPTX and JSON download links.
 * Features a polished loading animation during PPTX generation.
 * Integrates SpecStepNav for viewing brief/outline/art-direction content.
 */

"use client"

import { useState, useEffect, useRef } from "react"
import { SlidePreview, getDeckWithJson } from "@/services/deckService"
import type { SpecFiles } from "@/services/deckService"
import { Download, FileJson, Layers, Loader2, LayoutGrid, Rows3 } from "lucide-react"
import { useAuth } from "react-oidc-context"
import { usePreferences } from "@/hooks/usePreferences"
import { SpecStepNav, SpecMarkdownPreview } from "@/components/deck/SpecStepNav"
import type { SpecTab } from "@/components/deck/SpecStepNav"

interface SlideCarouselProps {
  slides: SlidePreview[]
  deckId?: string
  deckName?: string
  pptxUrl?: string | null
  isLoading?: boolean
  onSlideClick?: (pageNumber: number) => void
  /** Slide ID to scroll to on mount (from search result navigation). */
  scrollToSlide?: string
  /** Callback to clear scrollToSlide after scrolling. */
  onScrollComplete?: () => void
  /** Optional header actions (e.g. visibility toggle, share button). */
  headerActions?: React.ReactNode
  /** Owner alias to display. */
  ownerAlias?: string
  /** Spec files for the deck (null values = not yet created). */
  specs?: SpecFiles | null
  /** Workflow phase detected from tool calls — drives spec tab auto-switch. */
  workflowPhase?: string | null
}

export function SlideCarousel({ slides, deckId, deckName, pptxUrl, isLoading, onSlideClick, scrollToSlide, onScrollComplete, headerActions, ownerAlias, specs, workflowPhase }: SlideCarouselProps) {
  const slidesWithPreview = slides.filter((s) => s.previewUrl)
  const auth = useAuth()
  const [jsonLoading, setJsonLoading] = useState(false)
  const { viewMode, setViewMode } = usePreferences()
  const containerRef = useRef<HTMLDivElement>(null)

  /* ── Spec tab state + auto-focus ── */
  const [specTab, setSpecTab] = useState<SpecTab>("brief")
  const prevSpecsRef = useRef<SpecFiles | null | undefined>(null)

  /**
   * Auto-focus: when a spec file transitions from null to non-null,
   * switch to that tab. Priority: brief → outline → artDirection.
   * When slides appear (0 → 1+), switch to slides tab.
   */
  useEffect(() => {
    const prev = prevSpecsRef.current
    prevSpecsRef.current = specs
    if (!prev || !specs) return

    const order: (keyof SpecFiles)[] = ["brief", "outline", "artDirection"]
    for (const key of order) {
      if (prev[key] == null && specs[key] != null) {
        setSpecTab(key)
        return
      }
    }
  }, [specs])

  // Switch tab when workflow phase is detected from tool calls
  useEffect(() => {
    if (workflowPhase && ["brief", "outline", "artDirection", "slides"].includes(workflowPhase)) {
      setSpecTab(workflowPhase as SpecTab)
    }
  }, [workflowPhase])

  const prevSlideCountRef = useRef(slides.length)
  useEffect(() => {
    const prevCount = prevSlideCountRef.current
    prevSlideCountRef.current = slides.length
    if (prevCount === 0 && slides.length > 0) {
      setSpecTab("slides")
    }
  }, [slides.length])

  // Scroll to target slide when navigating from search results
  useEffect(() => {
    if (!scrollToSlide || !containerRef.current) return
    const el = containerRef.current.querySelector(`[data-slide-id="${scrollToSlide}"]`)
    if (el) {
      setTimeout(() => {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
        onScrollComplete?.()
      }, 300)
    }
  }, [scrollToSlide, slidesWithPreview.length, onScrollComplete])

  /**
   * Fetch slideJson on demand and trigger download.
   */
  async function handleJsonDownload() {
    if (!deckId || !auth.user?.id_token) return
    setJsonLoading(true)
    try {
      const data = await getDeckWithJson(deckId, auth.user.id_token)
      const jsonSlides = data.slides
        .filter((s) => s.slideJson)
        .map((s) => {
          try { return JSON.parse(s.slideJson!) } catch { return s.slideJson }
        })
      if (jsonSlides.length === 0) return
      const blob = new Blob([JSON.stringify(jsonSlides, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `${deckName || "deck"}.json`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setJsonLoading(false)
    }
  }

  /** Whether any spec file has content. */
  const hasSpecs = specs != null && (specs.brief != null || specs.outline != null || specs.artDirection != null)

  /**
   * Render the empty-slides placeholder (loading animation or static message).
   *
   * @returns JSX element for the empty slides state
   */
  function renderSlidesEmpty(): React.ReactNode {
    if (isLoading) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
          <div className="flex flex-col items-center gap-5">
            <div className="relative w-28 h-20">
              {/* Slides developing like photos — rising and fading in */}
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="absolute rounded-md border border-brand-teal/20 overflow-hidden"
                  style={{
                    width: 48,
                    height: 32,
                    left: i * 20,
                    bottom: 0,
                    animation: `build-develop 2.8s ease-in-out ${i * 0.35}s infinite`,
                  }}
                >
                  {/* Shimmer sweep across each card */}
                  <div className="absolute inset-0 bg-gradient-to-r from-transparent via-brand-teal/15 to-transparent"
                    style={{ animation: `build-shimmer 2.8s ease-in-out ${i * 0.35}s infinite` }}
                  />
                </div>
              ))}
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Building your slides</p>
              <p className="text-xs text-foreground-secondary mt-1">This usually takes a few seconds…</p>
            </div>
            <div className="w-40 h-1 rounded-full bg-white/[0.06] overflow-hidden">
              <div
                className="h-full rounded-full bg-brand-teal/60"
                style={{ animation: "progress-sweep 2.5s ease-in-out infinite" }}
              />
            </div>
          </div>
        </div>
      )
    }
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
        {workflowPhase === "slides" ? (
          <div className="flex flex-col items-center gap-5">
            <div className="relative w-24 h-16">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="absolute left-1/2 rounded-md border border-brand-teal/15"
                  style={{
                    width: 56,
                    height: 36,
                    bottom: i * 4,
                    "--fan-r": `${(i - 1.5) * 4}deg`,
                    background: `oklch(0.16 0.02 185 / ${0.7 - i * 0.12})`,
                    animation: `compose-fan 2.4s ease-in-out ${i * 0.15}s infinite`,
                  } as React.CSSProperties}
                />
              ))}
            </div>
            <p className="text-sm text-muted-foreground">Composing slides…</p>
          </div>
        ) : (
          <>
            <div className="w-14 h-14 rounded-2xl bg-muted flex items-center justify-center mb-4 text-muted-foreground/40">
              <Layers className="h-7 w-7" />
            </div>
            <p className="text-sm text-muted-foreground">Slide previews will appear here after generating a PPTX.</p>
          </>
        )}
      </div>
    )
  }

  /**
   * Render the slides content (grid or full view).
   *
   * @returns JSX element for the slides view
   */
  function renderSlidesContent(): React.ReactNode {
    if (slidesWithPreview.length === 0) return renderSlidesEmpty()

    return (
      <div ref={containerRef} className={`flex-1 overflow-y-auto px-6 py-6 ${viewMode === "grid" ? "" : "space-y-4"}`}>
        {viewMode === "grid" ? (
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
            {slidesWithPreview.map((slide, i) => (
              <button
                key={slide.slideId}
                data-slide-id={slide.slideId}
                type="button"
                onClick={() => onSlideClick?.(i + 1)}
                className="rounded-lg overflow-hidden border border-border/40 hover:border-border-hover hover:-translate-y-[1px] hover:shadow-[0_4px_16px_oklch(0_0_0/30%)] transition-all duration-200 relative group"
                aria-label={`Slide ${i + 1}`}
              >
                <img
                  src={slide.previewUrl!}
                  alt={`Slide ${i + 1} of ${slidesWithPreview.length}${deckName ? `: ${deckName}` : ""}`}
                  className="w-full pointer-events-none"
                />
                <span className="absolute bottom-1.5 right-2 text-[10px] font-medium text-white/30 group-hover:text-white/50 transition-colors">
                  {i + 1}
                </span>
              </button>
            ))}
          </div>
        ) : (
          slidesWithPreview.map((slide, i) => (
            <button
              key={slide.slideId}
              data-slide-id={slide.slideId}
              type="button"
              onClick={() => onSlideClick?.(i + 1)}
              className="slide-shadow rounded-lg overflow-hidden w-full text-left cursor-pointer hover:ring-2 hover:ring-primary/50 transition-shadow"
              aria-label={`Insert reference to slide ${i + 1}`}
            >
              <img
                src={slide.previewUrl!}
                alt={`Slide ${i + 1} of ${slidesWithPreview.length}${deckName ? `: ${deckName}` : ""}`}
                className="w-full pointer-events-none"
              />
            </button>
          ))
        )}
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Spec step navigation */}
      <SpecStepNav
        specs={specs}
        activeTab={specTab}
        onTabChange={setSpecTab}
        slideCount={slidesWithPreview.length}
      />

      {/* Header (shown only on Slides tab) */}
      {specTab === "slides" && (
        <div className="flex-none flex items-center justify-between px-5 py-3 border-b border-border/40">
          <div className="flex items-center gap-3">
            <div>
              <h2 className="text-sm font-medium truncate max-w-[200px]">
                {deckName || "Preview"}
              </h2>
              <p className="text-xs text-muted-foreground">
                {slidesWithPreview.length} {slidesWithPreview.length === 1 ? "slide" : "slides"}
                {ownerAlias && <span> · by {ownerAlias}</span>}
              </p>
            </div>
            {headerActions}
          </div>
          <div className="flex items-center gap-1">
            {/* View mode toggle */}
            <div className="flex items-center rounded-lg border border-border/40 p-0.5 mr-1">
              <button
                onClick={() => setViewMode("full")}
                className={`p-1.5 rounded-md transition-colors ${viewMode === "full" ? "bg-background-hover text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                aria-label="Full size view"
              >
                <Rows3 className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setViewMode("grid")}
                className={`p-1.5 rounded-md transition-colors ${viewMode === "grid" ? "bg-background-hover text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                aria-label="Grid view"
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </button>
            </div>
            {deckId && (
              <button
                onClick={handleJsonDownload}
                disabled={jsonLoading}
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md hover:bg-accent transition-colors disabled:opacity-50"
                aria-label="Download JSON"
              >
                {jsonLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileJson className="h-3.5 w-3.5" />}
                JSON
              </button>
            )}
            {pptxUrl && (
              <a
                href={pptxUrl}
                download
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground no-underline px-3 py-1.5 rounded-md hover:bg-accent transition-colors"
                aria-label="Download PPTX"
              >
                <Download className="h-3.5 w-3.5" />
                PPTX
              </a>
            )}
          </div>
        </div>
      )}

      {/* Content area */}
      {specTab === "slides" ? (
        renderSlidesContent()
      ) : (
        <SpecMarkdownPreview
          content={specs?.[specTab] ?? null}
          specName={specTab.charAt(0).toUpperCase() + specTab.slice(1)}
          specKey={specTab}
        />
      )}
    </div>
  )
}
