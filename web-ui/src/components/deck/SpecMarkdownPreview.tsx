// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SpecMarkdownPreview — Renders spec markdown content with editorial styling.
 * Outline uses the dedicated OutlineView timeline component.
 * Brief uses react-markdown with HEX color swatches.
 * Art Direction renders HTML via sandboxed iframe with an inline
 * style gallery (gallery → preview → result states).
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
import { fetchStyles, fetchStyleHtml, pinStyle, type StyleEntry } from "@/services/deckService"
import { OutlineView } from "./OutlineView"
import { StyleSlidePreview } from "@/components/StyleSlidePreview"
import { StyleCard } from "./StyleCard"
import { BriefWaiting, OutlineWaiting, ArtDirectionWaiting } from "./SpecWaiting"

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
