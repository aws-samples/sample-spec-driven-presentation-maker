// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleGalleryModal — Full-screen gallery for selecting a design style.
 *
 * Opens automatically when the agent calls list_styles. Each card shows
 * a miniature iframe preview of the style's cover slide. Clicking a card
 * opens a full preview; from there the user can select or go back.
 *
 * @param props.open - Whether the modal is visible
 * @param props.onClose - Callback to close without selecting
 * @param props.onSelect - Callback with selected style name
 * @param props.idToken - Cognito ID token for API call
 */

"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { X, ArrowLeft, Check } from "lucide-react"
import { fetchStyles, fetchStyleHtml, type StyleEntry } from "@/services/deckService"

interface StyleGalleryModalProps {
  open: boolean
  onClose: () => void
  onSelect: (styleName: string) => void
  idToken: string
}

export function StyleGalleryModal({ open, onClose, onSelect, idToken }: StyleGalleryModalProps) {
  const [styles, setStyles] = useState<StyleEntry[]>([])
  const [loading, setLoading] = useState(false)
  const loadedRef = useRef(false)
  const [preview, setPreview] = useState<{ name: string; html: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  useEffect(() => {
    if (!open || loadedRef.current) return
    let cancelled = false
    setLoading(true)
    fetchStyles(idToken).then((s) => {
      if (cancelled) return
      loadedRef.current = true
      setStyles(s)
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [open, idToken])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") {
      if (preview) setPreview(null)
      else onClose()
    }
  }, [onClose, preview])

  useEffect(() => {
    if (!open) return
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [open, handleKeyDown])

  const handleCardClick = async (name: string) => {
    setPreviewLoading(true)
    setPreview({ name, html: "" })
    const html = await fetchStyleHtml(name, idToken)
    setPreview({ name, html })
    setPreviewLoading(false)
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={() => { if (preview) setPreview(null); else onClose() }}
    >
      <div
        className="relative w-full max-w-5xl max-h-[85vh] mx-4 rounded-2xl border border-white/[0.08] overflow-hidden flex flex-col"
        style={{ background: "oklch(0.12 0.005 260 / 97%)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            {preview && (
              <button
                onClick={() => setPreview(null)}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-white/[0.06] transition-colors"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
            )}
            <div>
              <h2 className="text-sm font-semibold">{preview ? preview.name : "Choose a Style"}</h2>
              <p className="text-xs text-foreground-muted mt-0.5">
                {preview ? "Preview all slides — select to apply" : "Click a style to preview"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {preview && (
              <button
                onClick={() => onSelect(preview.name)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-teal text-primary-foreground hover:bg-brand-teal/90 transition-colors"
              >
                <Check className="h-3.5 w-3.5" />
                Select
              </button>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-white/[0.06] transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {preview ? (
            <StylePreview html={preview.html} loading={previewLoading} />
          ) : loading ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="aspect-[16/10] rounded-xl bg-white/[0.03] animate-pulse" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {styles.map((style, i) => (
                <StyleCard key={style.name} style={style} index={i} onClick={handleCardClick} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Full style preview — renders all slides via iframe.
 */
function StylePreview({ html, loading }: { html: string; loading: boolean }) {
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

  if (loading || !html) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
      </div>
    )
  }

  const ratio = containerWidth > 0 ? containerWidth / 1920 : 1

  return (
    <div ref={containerRef} className="overflow-x-hidden">
      <div style={{ width: containerWidth, height: 1080 * ratio * 10, overflow: "hidden" }}>
        <iframe
          srcDoc={html}
          sandbox="allow-same-origin"
          title="Style Preview"
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

/**
 * Individual style card with iframe cover preview.
 */
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
    >
      {/* Preview */}
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

      {/* Info */}
      <div className="px-3 py-2.5 border-t border-white/[0.04]">
        <p className="text-[13px] font-medium text-foreground group-hover:text-brand-teal transition-colors">{style.name}</p>
        {style.description && (
          <p className="text-[11px] text-foreground-muted mt-0.5 line-clamp-1">{style.description}</p>
        )}
      </div>
    </button>
  )
}
