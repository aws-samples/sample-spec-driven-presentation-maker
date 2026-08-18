// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlideCarousel — Vertical scroll layout for slide PNG previews with spec step navigation.
 * Shows all slides stacked vertically with PPTX download and folder open links.
 * Features a polished loading animation during PPTX generation.
 * Integrates SpecStepNav for viewing brief/outline/art-direction content.
 */

"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { SlidePreview } from "@/services/deckService"
import type { SpecFiles } from "@/services/deckService"
import { Download, Layers, LayoutGrid, Rows3, FolderOpen } from "lucide-react"
import { usePreferences } from "@/hooks/usePreferences"
import { SpecStepNav, SpecMarkdownPreview } from "@/components/deck/SpecStepNav"
import type { SpecTab } from "@/components/deck/SpecStepNav"
import { SlideThumbnail } from "@/components/deck/SlideThumbnail"
import { AnimatedSlidePreview } from "@/components/deck/AnimatedSlidePreview"
import { IS_LOCAL } from "@/lib/mode"
import { notifyError } from "@/lib/errors"
import { useTranslations } from "next-intl"
import { AGENT_WAIT_COLORS } from "@/components/deck/SpecWaiting"


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
  /** Callback when user selects a template inline (isChange = template already confirmed). */
  onTemplateSelect?: (name: string, isChange: boolean) => void
  /** Confirmed template from deck.json (raw value, e.g. "corporate.pptx"). */
  currentTemplate?: string | null
  /** Cognito ID token for style API calls. */
  idToken?: string
}

export function SlideCarousel({ slides, defsUrl, deckId, deckName, pptxUrl, isLoading, onSlideClick, scrollToSlide, onScrollComplete, headerActions, ownerAlias, specs, workflowPhase, onStyleSelect, onTemplateSelect, currentTemplate, idToken }: SlideCarouselProps) {
  const t = useTranslations("carousel")
  const slidesWithPreview = slides.filter((s) => s.previewUrl || s.composeUrl)
  const slugs = slides.map(s => s.slug)
  if (new Set(slugs).size !== slugs.length) console.warn("[SlideCarousel] duplicate slugs:", slugs)
  // Check compose URL duplicates across different slugs
  const urlBySlug: Record<string,string> = {}
  const dupUrls: string[] = []
  for (const s of slidesWithPreview) {
    const u = s.composeUrl?.split("?")[0] || ""
    if (u && Object.values(urlBySlug).includes(u)) dupUrls.push(`${s.slug}→${u}`)
    if (u) urlBySlug[s.slug] = u
  }
  if (dupUrls.length) console.warn("[SlideCarousel] same composeUrl used for multiple slides:", dupUrls, urlBySlug)
  const { viewMode, setViewMode } = usePreferences()
  const containerRef = useRef<HTMLDivElement>(null)

  /* ── Aspect ratio reported by the first child (deck is uniform) ── */
  const [deckAr, setDeckAr] = useState(16 / 9)
  const arReported = useRef(false)
  const handleAspectRatio = useCallback((ratio: number) => {
    if (!arReported.current && ratio > 0) {
      arReported.current = true
      setDeckAr(ratio)
    }
  }, [])

  /* ── Compose update detection → auto-scroll to changed slide ── */
  const prevComposeKeys = useRef<Map<string, string>>(new Map())
  const scrollTargetRef = useRef<string | null | undefined>(undefined)
  const hadSlidesOnMount = useRef(slides.length > 0)
  const [firstComposeSeen, setFirstComposeSeen] = useState(false)
  const [knownComposeUrls, setKnownComposeUrls] = useState<Map<string, string>>(new Map())

  useEffect(() => {
    let anyChanged = false
    for (const slide of slides) {
      const key = slide.composeUrl?.split("?")[0] || ""
      const prev = prevComposeKeys.current.get(slide.slug) || ""
      if (key && prev && key !== prev) anyChanged = true
      if (key && !prev && firstComposeSeen) anyChanged = true
      if (key) prevComposeKeys.current.set(slide.slug, key)
    }
    // Mark first compose seen (skip animation for existing decks)
    if (!firstComposeSeen && slides.some(s => s.composeUrl)) {
      if (hadSlidesOnMount.current) {
        // Existing deck: suppress animation for this first batch
        anyChanged = false
      }
      setFirstComposeSeen(true)
    }
    if (anyChanged) scrollTargetRef.current = null // arm scroll for next onAnimate
    setKnownComposeUrls(new Map(prevComposeKeys.current))
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
  async function handleFolderOpen() {
    if (!deckId || !IS_LOCAL) return
    fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deckId }) }).catch((err) => notifyError(t("errorOpenFolder"), err, { retry: handleFolderOpen }))
  }

  /** Local: open output.pptx with default app */
  async function handlePptxOpen() {
    if (!deckId || !IS_LOCAL) return
    fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deckId, file: "output.pptx" }) }).catch((err) => notifyError(t("errorOpenPptx"), err, { retry: handlePptxOpen }))
  }

  /**
   * Render the empty-slides placeholder (loading animation or static message).
   *
   * @returns JSX element for the empty slides state
   */
  // Use the shared five agent identity colors for waiting animations.
  const WAIT_COLORS = AGENT_WAIT_COLORS.map((c) => c.css)

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
                      background: `linear-gradient(90deg, transparent, color-mix(in oklch, ${WAIT_COLORS[i]} 25%, transparent), transparent)`,
                      opacity: 0.35,
                      animation: `build-shimmer 2.8s ease-in-out ${i * 0.3}s infinite`,
                    }}
                  />
                </div>
              ))}
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">{t("buildingSlides")}</p>
              <p className="text-xs text-foreground-secondary mt-1">{t("buildingHint")}</p>
            </div>
            <div className="w-48 h-1.5 rounded-full bg-foreground/[0.06] overflow-hidden">
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
                      boxShadow: `0 0 12px color-mix(in oklch, ${color} 19%, transparent)`,
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
            <p className="text-sm text-muted-foreground">{t("composing")}</p>
          </div>
        ) : (
          <>
            <div className="w-14 h-14 rounded-2xl bg-muted flex items-center justify-center mb-4 text-muted-foreground/40">
              <Layers className="h-7 w-7" />
            </div>
            <p className="text-sm text-muted-foreground">{t("previewsPlaceholder")}</p>
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
      <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-6">
        {viewMode === "grid" ? (
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
            {slidesWithPreview.map((slide, i) => (
              <SlideThumbnail
                key={slide.slug}
                src={slide.previewUrl}
                alt={t("slideAltFull", { number: i + 1, total: slidesWithPreview.length }) + (deckName ? `: ${deckName}` : "")}
                index={i}
                slug={slide.slug}
                onClick={() => onSlideClick?.(i + 1)}
                updated={updatedIds.has(slide.slug)}
                className="border border-border/40 hover:border-border-hover hover:-translate-y-[1px] hover:shadow-[0_4px_16px_oklch(0_0_0/30%)] transition-all duration-200 cursor-pointer group"
              >

                <span className="absolute bottom-1.5 right-2 text-[11px] font-medium text-white/30 group-hover:text-white/50 transition-colors">
                  {i + 1}
                </span>
              </SlideThumbnail>
            ))}
          </div>
        ) : (
          /* Full view: cap height so one slide always fits the viewport
             (100vh minus header + paddings). Width follows aspect ratio. */
          <div className="mx-auto w-full space-y-4"
               style={{ maxWidth: `calc((100vh - 170px) * ${deckAr})` }}>
          {slidesWithPreview.map((slide, i) => (
            slide.composeUrl && defsUrl ? (
              <AnimatedSlidePreview
                key={slide.slug}
                defsUrl={defsUrl}
                composeUrl={slide.composeUrl}
                slug={slide.slug}
                skipAnimation={hadSlidesOnMount.current && !firstComposeSeen}
                knownUrl={hadSlidesOnMount.current ? (knownComposeUrls.get(slide.slug) || null) : null}
                onAnimate={() => handleAnimate(slide.slug)}
                onAspectRatio={handleAspectRatio}
                fallback={
                  <SlideThumbnail
                    src={slide.previewUrl}
                    alt={t("slideAlt", { number: i + 1 })}
                    index={i}
                    slug={slide.slug}
                    onClick={() => onSlideClick?.(i + 1)}
                    onAspectRatio={handleAspectRatio}
                    className="slide-shadow w-full cursor-pointer hover:ring-2 hover:ring-primary/50 transition-shadow"
                  />
                }
              />
            ) : (
              <SlideThumbnail
                key={slide.slug}
                src={slide.previewUrl}
                alt={t("slideAltFull", { number: i + 1, total: slidesWithPreview.length }) + (deckName ? `: ${deckName}` : "")}
                index={i}
                slug={slide.slug}
                onClick={() => onSlideClick?.(i + 1)}
                updated={updatedIds.has(slide.slug)}
                onAspectRatio={handleAspectRatio}
                className="slide-shadow w-full cursor-pointer hover:ring-2 hover:ring-primary/50 transition-shadow"
              />
            )
          ))}
          </div>
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
                {deckName || t("preview")}
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
                aria-label={t("fullSizeView")}
              >
                <Rows3 className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setViewMode("grid")}
                className={`p-1.5 rounded-md transition-colors ${viewMode === "grid" ? "bg-background-hover text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                aria-label={t("gridView")}
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </button>
            </div>
            {IS_LOCAL && deckId && (
              <button
                onClick={handleFolderOpen}
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md hover:bg-accent transition-colors"
                aria-label={t("openFolder")}
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
                  aria-label={t("openPptx")}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  PPTX
                </button>
              ) : (
                <a
                  href={pptxUrl}
                  download
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground no-underline px-3 py-1.5 rounded-md hover:bg-accent transition-colors"
                  aria-label={t("downloadPptx")}
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
          onTemplateSelect={specTab === "artDirection" ? onTemplateSelect : undefined}
          currentTemplate={specTab === "artDirection" ? currentTemplate : undefined}
          idToken={specTab === "artDirection" ? idToken : undefined}
          outlineExists={specTab === "brief" ? (specs?.outline != null) : undefined}
        />
      )}
    </div>
  )
}
