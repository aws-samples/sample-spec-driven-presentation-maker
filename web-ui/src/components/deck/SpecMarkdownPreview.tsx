// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SpecMarkdownPreview — Renders spec markdown content with editorial styling.
 * Outline uses the dedicated OutlineView timeline component.
 * Brief uses react-markdown with HEX color swatches.
 * Art Direction renders a persistent template picker section (header-like,
 * non-sticky) above an inline style gallery (gallery → preview → result
 * states). Both sections share one scroll container but keep independent
 * display states.
 *
 * @param props.content - Markdown or HTML string to render
 * @param props.specName - Name of the spec (for empty state)
 * @param props.specKey - Which spec tab ("brief" | "outline" | "artDirection")
 */

"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { FileText, Palette, ArrowLeft, Check, Star } from "lucide-react"
import Markdown from "react-markdown"
import type { Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { fetchStyles, pinStyle, type StyleEntry } from "@/services/deckService"
import { OutlineView } from "./OutlineView"
import { StyleSlidePreview, splitStyleSlides } from "@/components/StyleSlidePreview"
import { StyleCard } from "./StyleCard"
import { TemplatePickerSection } from "./TemplatePickerSection"
import { BriefWaiting, OutlineWaiting, ArtDirectionWaiting } from "./SpecWaiting"
import { BriefDocumentView } from "./BriefDocumentView"
import { renderColorSwatches } from "./colorSwatches"
import { useTranslations } from "next-intl"

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
            className="inline-block w-3 h-3 rounded-full border border-border-hover flex-none"
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

export function SpecMarkdownPreview({ content, specName, specKey, onStyleSelect, onTemplateSelect, currentTemplate, idToken, outlineExists }: { content: string | null; specName: string; specKey?: string; onStyleSelect?: (name: string) => void; onTemplateSelect?: (name: string, isChange: boolean) => void; currentTemplate?: string | null; idToken?: string; outlineExists?: boolean }) {
  const t = useTranslations("stylePicker")
  // Hooks must be called unconditionally — before any early returns.

  // Art Direction inline gallery state
  type ArtDirectionMode = "gallery" | "preview" | "result"
  const [adMode, setAdMode] = useState<ArtDirectionMode>(content ? "result" : "gallery")
  const [styles, setStyles] = useState<StyleEntry[]>([])
  const [stylesLoading, setStylesLoading] = useState(false)
  const stylesLoadedRef = useRef(false)
  const [preview, setPreview] = useState<{ name: string; html: string } | null>(null)
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

  // Art Direction: template section (persistent) + style section (3-state)
  // sharing one scroll container. The template picker is header-like and
  // independent of the style state machine — it stays visible in all states.
  if (specKey === "artDirection") {
    const wrap = (body: React.ReactNode) => (
      <div ref={galleryContainerRef} className="flex-1 overflow-y-auto overflow-x-hidden flex flex-col">
        {onTemplateSelect && (
          <TemplatePickerSection idToken={idToken} currentTemplate={currentTemplate} onTemplateSelect={onTemplateSelect} />
        )}
        <div className="flex-1 flex flex-col min-h-0">{body}</div>
      </div>
    )

    // Waiting state (no content, not browsing styles)
    if (!content && adMode === "result") {
      return wrap(
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
        const style = styles.find(s => s.name === name)
        const html = style?.html || ""
        setPreview({ name, html })
        setAdMode("preview")
      }

      const pinnedStyles = styles.filter(s => s.pinned)
      const hasPins = pinnedStyles.length > 0
      const unpinnedStyles = styles.filter(s => !s.pinned)

      return wrap(
        <div>
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-border">
            <div>
              <h2 className="text-[15px] font-semibold">{t("chooseStyle")}</h2>
              <p className="text-xs text-foreground-muted mt-0.5">{t("clickToPreview")}</p>
            </div>
            {content && (
              <button
                onClick={() => { userRequestedGallery.current = false; setAdMode("result") }}
                className="inline-flex items-center gap-1.5 text-xs text-foreground-muted hover:text-foreground px-3 py-1.5 rounded-lg border border-border hover:bg-foreground/[0.06] transition-colors"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                {t("backToArtDirection")}
              </button>
            )}
          </div>
          {/* Grid */}
          <div className="p-6">
            {stylesLoading ? (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="aspect-[16/10] rounded-xl bg-foreground/[0.03] animate-pulse" />
                ))}
              </div>
            ) : hasPins ? (
              /* Sectioned layout: Pinned + All Styles collapsible */
              <div className="flex flex-col gap-6">
                {/* Pinned section */}
                <div>
                  <div className="flex items-center gap-1.5 mb-3">
                    <Star className="h-3.5 w-3.5 text-brand-teal" fill="currentColor" />
                    <h3 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">{t("pinned")}</h3>
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
                    {t("allStyles", { count: unpinnedStyles.length })}
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

      return wrap(
        <div>
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-border">
            <div className="flex items-center gap-3">
              <button
                onClick={() => { setPreview(null); setAdMode("gallery"); }}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-foreground/[0.06] transition-colors"
                aria-label={t("backToStylesAria")}
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <div className="flex items-center gap-2">
                <h2 className="text-[15px] font-semibold">{preview.name}</h2>
                <button
                  onClick={() => handlePinToggle(preview.name)}
                  className={`p-1 rounded transition-colors ${previewPinned ? "text-brand-teal" : "text-foreground-muted hover:text-foreground"}`}
                  aria-label={previewPinned ? t("unpinAria", { name: preview.name }) : t("pinAria", { name: preview.name })}
                >
                  <Star className="h-3.5 w-3.5" fill={previewPinned ? "currentColor" : "none"} />
                </button>
              </div>
              <p className="text-xs text-foreground-muted">{t("previewHint")}</p>
            </div>
            <button
              onClick={handleSelect}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-teal text-primary-foreground hover:bg-brand-teal/90 transition-colors"
            >
              <Check className="h-3.5 w-3.5" />
              {t("select")}
            </button>
          </div>
          {/* Preview content */}
          <div className="p-6">
            <StyleSlidePreview html={preview.html} loading={false} />
          </div>
        </div>
      )
    }

    // RESULT state (default when content exists)
    const isHtml = content!.trim().startsWith("<")
    const sampleCount = isHtml ? (splitStyleSlides(content!)?.slides.length ?? 0) : 0
    return wrap(
      <section className="px-6 pt-4 pb-6">
        <div className="max-w-4xl mx-auto">
          {/* Section header — same grammar as the template section above */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-baseline gap-2.5">
              <h3 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">{t("sectionTitle")}</h3>
              {sampleCount > 0 && (
                <span className="text-xs text-foreground-muted">{t("sampleCount", { count: sampleCount })}</span>
              )}
            </div>
            {onStyleSelect && (
              <button
                onClick={() => { userRequestedGallery.current = true; setAdMode("gallery") }}
                className="inline-flex items-center gap-1.5 text-xs text-foreground-muted hover:text-foreground px-3 py-1.5 rounded-lg border border-border hover:bg-foreground/[0.06] transition-colors"
              >
                <Palette className="h-3.5 w-3.5" />
                {t("changeStyle")}
              </button>
            )}
          </div>
          {isHtml ? (
            <StyleSlidePreview html={content!} loading={false} />
          ) : (
            <article className="document-surface prose prose-invert prose-sm max-w-3xl spec-prose">
              <Markdown remarkPlugins={[remarkGfm]} components={specComponents as Components}>
                {content!}
              </Markdown>
            </article>
          )}
        </div>
      </section>
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

  // Brief tab: use the contract-document metaphor with approval status
  if (specKey === "brief") {
    return (
      <BriefDocumentView
        content={content}
        outlineExists={outlineExists ?? false}
      />
    )
  }

  return (
    <div className="content-enter flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      <article className="document-surface prose prose-invert prose-sm max-w-3xl mx-auto spec-prose">
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
