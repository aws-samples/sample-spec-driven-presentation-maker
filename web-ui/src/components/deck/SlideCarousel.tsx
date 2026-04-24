// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlideCarousel — Vertical scroll layout for slide PNG previews with spec step navigation.
 * Shows all slides stacked vertically with PPTX and JSON download links.
 * Features a polished loading animation during PPTX generation.
 * Integrates SpecStepNav for viewing brief/outline/art-direction content.
 */

"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { SlidePreview } from "@/services/deckService"
import type { SpecFiles } from "@/services/deckService"
import { Download, Layers, Loader2, LayoutGrid, Rows3, FolderOpen } from "lucide-react"
import { useAuth } from "@/hooks/useAuth"
import { usePreferences } from "@/hooks/usePreferences"
import { SpecStepNav, SpecMarkdownPreview } from "@/components/deck/SpecStepNav"
import type { SpecTab } from "@/components/deck/SpecStepNav"
import { SlideThumbnail } from "@/components/deck/SlideThumbnail"
import { AnimatedSlidePreview } from "@/components/deck/AnimatedSlidePreview"
import { CloudOnly, LocalOnly, IS_LOCAL } from "@/lib/mode"


interface SlideCarouselProps {
  slides: SlidePreview[]
  defsUrl?: string | null
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
  /** Callback when user selects a style inline. */
  onStyleSelect?: (name: string) => void
  /** Cognito ID token for style API calls. */
  idToken?: string
}

export function SlideCarousel({ slides, defsUrl, deckId, deckName, pptxUrl, isLoading, onSlideClick, scrollToSlide, onScrollComplete, headerActions, ownerAlias, specs, workflowPhase, onStyleSelect, idToken }: SlideCarouselProps) {
  const slidesWithPreview = slides.filter((s) => s.previewUrl || s.composeUrl)
  // eslint-disable-next-line no-console
  const slugs = slides.map(s => s.slug)
  // eslint-disable-next-line no-console
  if (new Set(slugs).size !== slugs.length) console.warn("[SlideCarousel] duplicate slugs:", slugs)
  // Check compose URL duplicates across different slugs
  // eslint-disable-next-line no-console
  const urlBySlug: Record<string,string> = {}
  const dupUrls: string[] = []
  for (const s of slidesWithPreview) {
    const u = s.composeUrl?.split("?")[0] || ""
    if (u && Object.values(urlBySlug).includes(u)) dupUrls.push(`${s.slug}→${u}`)
    if (u) urlBySlug[s.slug] = u
  }
  // eslint-disable-next-line no-console
  if (dupUrls.length) console.warn("[SlideCarousel] same composeUrl used for multiple slides:", dupUrls, urlBySlug)
  // eslint-disable-next-line no-console
  console.log("[SlideCarousel] slug→url:", slidesWithPreview.map(s => `${s.slug}: ${s.composeUrl?.split("/").pop()?.split("?")[0]}`))
  const auth = useAuth()
  const { viewMode, setViewMode } = usePreferences()
  const containerRef = useRef<HTMLDivElement>(null)

  /* ── Compose update detection → auto-scroll to changed slide ── */
  const prevComposeKeys = useRef<Map<string, string>>(new Map())
  const scrollTargetRef = useRef<string | null | undefined>(undefined)
  const hadSlidesOnMount = useRef(slides.length > 0)
  const firstComposeSeenRef = useRef(false)

  useEffect(() => {
    let anyChanged = false
    for (const slide of slides) {
      const key = slide.composeUrl?.split("?")[0] || ""
      const prev = prevComposeKeys.current.get(slide.slug) || ""
      if (key && prev && key !== prev) anyChanged = true
      if (key && !prev && firstComposeSeenRef.current) anyChanged = true
      if (key) prevComposeKeys.current.set(slide.slug, key)
    }
    // Mark first compose seen (skip animation for existing decks)
    if (!firstComposeSeenRef.current && slides.some(s => s.composeUrl)) {
      if (hadSlidesOnMount.current) {
        // Existing deck: suppress animation for this first batch
        anyChanged = false
      }
      firstComposeSeenRef.current = true
    }
    if (anyChanged) scrollTargetRef.current = null // arm scroll for next onAnimate
  }, [slides])

  const handleAnimate = useCallback((slug: string) => {
    if (scrollTargetRef.current === null && containerRef.current) {
      scrollTargetRef.current = slug
      const el = containerRef.current.querySelector(`[data-slide-id="${slug}"]`)
      if (el) {
        const container = containerRef.current
        const elRect = el.getBoundingClientRect()
        const containerRect = container.getBoundingClientRect()
        const offset = elRect.top - containerRect.top + container.scrollTop - 24
        container.scrollTo({ top: offset, behavior: "smooth" })
      }
    }
  }, [])

  /* ── Slide update detection for glow highlight ── */
  const prevUrlKeys = useRef<Map<string, string>>(new Map())
  const [updatedIds, setUpdatedIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    const newUpdated = new Set<string>()
    for (const slide of slides) {
      const newKey = slide.previewUrl?.split("?")[0] || ""
      const prevKey = prevUrlKeys.current.get(slide.slug) || ""
      if (prevKey && newKey && newKey !== prevKey) {
        newUpdated.add(slide.slug)
      }
      if (newKey) prevUrlKeys.current.set(slide.slug, newKey)
    }
    if (newUpdated.size > 0) {
      setUpdatedIds(newUpdated)
      const timer = setTimeout(() => setUpdatedIds(new Set()), 1500)
      return () => clearTimeout(timer)
    }
  }, [slides])

  /* ── Spec tab state + auto-focus ── */
  const [specTab, setSpecTab] = useState<SpecTab>("brief")
  const prevSpecsRef = useRef<SpecFiles | null | undefined>(null)
  // Suppress animation for 3s after slides tab becomes visible
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    if (specTab !== "slides") { setSettled(false); return }
    const t = setTimeout(() => setSettled(true), 3000)
    return () => clearTimeout(t)
  }, [specTab])

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

  /** Local: open deck directory in Finder/Explorer */
  async function handleJsonOpen() {
    if (!deckId || !IS_LOCAL) return
    fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deckId }) }).catch(() => {})
  }

  /** Local: open output.pptx with default app */
  async function handlePptxOpen() {
    if (!deckId || !IS_LOCAL) return
    fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deckId, file: "output.pptx" }) }).catch(() => {})
  }

  /**
   * Render the empty-slides placeholder (loading animation or static message).
   *
   * @returns JSX element for the empty slides state
   */
  const WAIT_COLORS = [
    "oklch(0.75 0.14 185)", "oklch(0.82 0.16 75)",
    "oklch(0.70 0.18 330)", "oklch(0.78 0.15 145)",
  ]

  function renderSlidesEmpty(): React.ReactNode {
    if (isLoading) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
          <div className="build-waiting flex flex-col items-center gap-6">
            <div className="relative" style={{ width: 200, height: 80 }}>
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="build-card absolute rounded-lg overflow-hidden"
                  style={{
                    width: 72,
                    height: 48,
                    left: i * 34,
                    bottom: 0,
                    border: `1.5px solid ${WAIT_COLORS[i]}`,
                    "--card-color": WAIT_COLORS[i],
                    animation: `build-develop 2.8s ease-in-out ${i * 0.3}s infinite, build-glow-pulse 2.8s ease-in-out ${i * 0.3}s infinite`,
                  } as React.CSSProperties}
                >
                  <div
                    className="build-shimmer-el absolute inset-0"
                    style={{
                      background: `linear-gradient(90deg, transparent, ${WAIT_COLORS[i]}40, transparent)`,
                      opacity: 0.35,
                      animation: `build-shimmer 2.8s ease-in-out ${i * 0.3}s infinite`,
                    }}
                  />
                </div>
              ))}
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Building your slides</p>
              <p className="text-xs text-foreground-secondary mt-1">This usually takes a few seconds…</p>
            </div>
            <div className="w-48 h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  background: `linear-gradient(90deg, ${WAIT_COLORS[0]}, ${WAIT_COLORS[1]})`,
                  animation: "progress-sweep 2.5s ease-in-out infinite",
                }}
              />
            </div>
          </div>
        </div>
      )
    }
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
        {workflowPhase === "slides" ? (
          <div className="compose-waiting flex flex-col items-center gap-6">
            <div className="relative" style={{ width: 160, height: 100 }}>
              {[0, 1, 2, 3].map((i) => {
                const color = WAIT_COLORS[i]
                return (
                  <div
                    key={i}
                    className="compose-card absolute left-1/2 rounded-lg overflow-hidden"
                    style={{
                      width: 80,
                      height: 50,
                      bottom: i * 5,
                      "--fan-r": `${(i - 1.5) * 8}deg`,
                      border: `1.5px solid ${color}`,
                      background: `oklch(0.14 0.01 260 / ${0.8 - i * 0.1})`,
                      boxShadow: `0 0 12px ${color}30`,
                      animation: `compose-fan 2.4s ease-in-out ${i * 0.15}s infinite`,
                    } as React.CSSProperties}
                  >
                    {/* Inner content lines */}
                    <div className="p-1.5 flex flex-col gap-1">
                      {[0, 1, 2].map((j) => (
                        <div
                          key={j}
                          className="h-[2.5px] rounded-full"
                          style={{
                            width: `${70 - j * 15}%`,
                            background: color,
                            opacity: 0.3,
                            animation: `compose-inner-line 2.4s ease-in-out ${i * 0.15 + j * 0.2}s infinite`,
                          }}
                        />
                      ))}
                    </div>
                  </div>
                )
              })}
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
              <SlideThumbnail
                key={slide.slug}
                src={slide.previewUrl}
                alt={`Slide ${i + 1} of ${slidesWithPreview.length}${deckName ? `: ${deckName}` : ""}`}
                index={i}
                slug={slide.slug}
                onClick={() => onSlideClick?.(i + 1)}
                updated={updatedIds.has(slide.slug)}
                className="border border-border/40 hover:border-border-hover hover:-translate-y-[1px] hover:shadow-[0_4px_16px_oklch(0_0_0/30%)] transition-all duration-200 cursor-pointer group"
              >

                <span className="absolute bottom-1.5 right-2 text-[10px] font-medium text-white/30 group-hover:text-white/50 transition-colors">
                  {i + 1}
                </span>
              </SlideThumbnail>
            ))}
          </div>
        ) : (
          slidesWithPreview.map((slide, i) => (
            slide.composeUrl && defsUrl ? (
              <AnimatedSlidePreview
                key={slide.slug}
                defsUrl={defsUrl}
                composeUrl={slide.composeUrl}
                slug={slide.slug}
                skipAnimation={!settled || (hadSlidesOnMount.current && !firstComposeSeenRef.current)}
                onAnimate={() => handleAnimate(slide.slug)}
                fallback={
                  <SlideThumbnail
                    src={slide.previewUrl}
                    alt={`Slide ${i + 1}`}
                    index={i}
                    slug={slide.slug}
                    onClick={() => onSlideClick?.(i + 1)}
                    className="slide-shadow w-full cursor-pointer hover:ring-2 hover:ring-primary/50 transition-shadow"
                  />
                }
              />
            ) : (
              <SlideThumbnail
                key={slide.slug}
                src={slide.previewUrl}
                alt={`Slide ${i + 1} of ${slidesWithPreview.length}${deckName ? `: ${deckName}` : ""}`}
                index={i}
                slug={slide.slug}
                onClick={() => onSlideClick?.(i + 1)}
                updated={updatedIds.has(slide.slug)}
                className="slide-shadow w-full cursor-pointer hover:ring-2 hover:ring-primary/50 transition-shadow"
              />
            )
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
            {IS_LOCAL && deckId && (
              <button
                onClick={handleJsonOpen}
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md hover:bg-accent transition-colors"
                aria-label="Open folder"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                Folder
              </button>
            )}
            {pptxUrl && (
              IS_LOCAL ? (
                <button
                  onClick={handlePptxOpen}
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md hover:bg-accent transition-colors"
                  aria-label="Open PPTX"
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  PPTX
                </button>
              ) : (
                <a
                  href={pptxUrl}
                  download
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground no-underline px-3 py-1.5 rounded-md hover:bg-accent transition-colors"
                  aria-label="Download PPTX"
                >
                  <Download className="h-3.5 w-3.5" />
                  PPTX
                </a>
              )
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
          onStyleSelect={specTab === "artDirection" ? onStyleSelect : undefined}
          idToken={specTab === "artDirection" ? idToken : undefined}
        />
      )}
    </div>
  )
}
