// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleGalleryModal — Full-screen gallery for selecting a design style.
 *
 * Opens automatically when the agent calls list_styles. Each card shows
 * a miniature iframe preview of the style's cover slide. Clicking a card
 * selects the style and closes the modal.
 *
 * @param props.open - Whether the modal is visible
 * @param props.onClose - Callback to close without selecting
 * @param props.onSelect - Callback with selected style name
 * @param props.idToken - Cognito ID token for API call
 */

"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { X } from "lucide-react"
import { fetchStyles, type StyleEntry } from "@/services/deckService"

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
    if (e.key === "Escape") onClose()
  }, [onClose])

  useEffect(() => {
    if (!open) return
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-5xl max-h-[85vh] mx-4 rounded-2xl border border-white/[0.08] overflow-hidden flex flex-col"
        style={{ background: "oklch(0.12 0.005 260 / 97%)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div>
            <h2 className="text-sm font-semibold">Choose a Style</h2>
            <p className="text-xs text-foreground-muted mt-0.5">Click a style to apply it to your presentation</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-white/[0.06] transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="aspect-[16/10] rounded-xl bg-white/[0.03] animate-pulse" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {styles.map((style, i) => (
                <StyleCard key={style.name} style={style} index={i} onSelect={onSelect} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Individual style card with iframe cover preview.
 *
 * @param props.style - Style entry with name, description, coverHtml
 * @param props.index - Card index for stagger animation
 * @param props.onSelect - Selection callback
 */
function StyleCard({ style, index, onSelect }: { style: StyleEntry; index: number; onSelect: (name: string) => void }) {
  // iframe is 1920px wide, scaled down to fit card
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
      onClick={() => onSelect(style.name)}
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
        {/* Hover overlay */}
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
