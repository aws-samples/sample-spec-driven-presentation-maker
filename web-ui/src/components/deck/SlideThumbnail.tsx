// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlideThumbnail — Skeleton → reveal transition for a single slide preview.
 *
 * Shows a shimmer skeleton placeholder until the image loads, then reveals
 * with a staggered scale+fade animation. On src change (measure/generate
 * update), resets to skeleton to maintain layout height and prevent scroll
 * position shifts.
 *
 * The aspect ratio adapts to the actual image dimensions (detected via
 * onLoad naturalWidth/naturalHeight). Falls back to 16/9 before the first
 * image has loaded.
 *
 * HTML deck previews (`preview/<slug>.html`) render in a `sandbox=""` iframe
 * (HtmlSlideFrame) at the deck's `slideSize` instead of an <img>.
 */

"use client"

import { useState, useEffect } from "react"
import { isHtmlPreview } from "@/lib/preview"
import { HtmlSlideFrame } from "@/components/deck/HtmlSlideFrame"

interface SlideThumbnailProps {
  src: string | null
  alt: string
  index: number
  onClick?: () => void
  className?: string
  updated?: boolean
  /** data-slide-id for scroll-to-slide targeting. */
  slug?: string
  /** Report detected aspect ratio to parent. */
  onAspectRatio?: (ratio: number) => void
  /** Called when the image fails to load (e.g. 403). */
  onError?: () => void
  /** HTML decks: canvas size, which sets the thumbnail's aspect ratio. */
  slideSize?: { width: number; height: number }
  children?: React.ReactNode
}

export function SlideThumbnail({ src, alt, index, onClick, className, updated, slug, onAspectRatio, onError, slideSize, children }: SlideThumbnailProps) {
  const [aspectRatio, setAspectRatio] = useState<string>("16/9")
  // `shown` is the image currently on screen; `incoming` is a newer src still
  // loading. The old image stays until the new one is ready, then they crossfade,
  // so a regenerate never flashes the skeleton.
  const [shown, setShown] = useState<{ src: string; loaded: boolean } | null>(src ? { src, loaded: false } : null)
  const [incoming, setIncoming] = useState<string | null>(null)
  const [outgoing, setOutgoing] = useState<string | null>(null)

  useEffect(() => {
    if (!src) { setShown(null); setIncoming(null); return }
    if (!shown) { setShown({ src, loaded: false }); return }
    if (src !== shown.src) setIncoming(src)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src])

  useEffect(() => {
    if (!outgoing) return
    const timer = setTimeout(() => setOutgoing(null), 300)
    return () => clearTimeout(timer)
  }, [outgoing])
  // The update glow runs when the new image is actually on screen, not when
  // its URL changed (the file may still be loading then).
  const [glow, setGlow] = useState(false)
  useEffect(() => {
    if (!glow) return
    const timer = setTimeout(() => setGlow(false), 1500)
    return () => clearTimeout(timer)
  }, [glow])

  const readAspect = (img: HTMLImageElement) => {
    if (img.naturalWidth > 0 && img.naturalHeight > 0) {
      setAspectRatio(`${img.naturalWidth}/${img.naturalHeight}`)
      onAspectRatio?.(img.naturalWidth / img.naturalHeight)
    }
  }
  const html = isHtmlPreview(src)
  const slideWidth = slideSize?.width ?? 1920
  const slideHeight = slideSize?.height ?? 1080
  useEffect(() => {
    if (html && slideWidth > 0 && slideHeight > 0) onAspectRatio?.(slideWidth / slideHeight)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html, slideWidth, slideHeight])

  // Reveal stagger only for the first screenful; a 30-slide deck must not make
  // its last slide wait 1.8 s after it has loaded.
  const revealDelay = `${Math.min(index, 6) * 60}ms`

  return (
    <div
      className={`relative overflow-hidden rounded-lg ${updated || glow ? "slide-updated" : ""} ${className || ""}`}
      style={{ aspectRatio: html ? `${slideWidth}/${slideHeight}` : aspectRatio }}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick() } } : undefined}
      data-slide-id={slug}
    >
      {html && src ? (
        <HtmlSlideFrame src={src} title={alt} width={slideWidth} height={slideHeight} />
      ) : (
      <>
      {/* Skeleton layer — only before the first image has ever loaded */}
      {shown && !shown.loaded && <div className="slide-skeleton absolute inset-0" />}

      {/* Explicit placeholder when no src is available */}
      {!src && (
        <div className="absolute inset-0 flex items-center justify-center bg-muted/30" data-placeholder>
          <span className="text-xs text-muted-foreground">Preview unavailable</span>
        </div>
      )}

      {/* Previous image, fading out under the new one */}
      {outgoing && (
        <img src={outgoing} alt="" aria-hidden className="absolute inset-0 w-full h-full object-contain slide-swap-out" data-outgoing />
      )}

      {/* Image on screen */}
      {shown && (
        <img
          key={shown.src}
          src={shown.src}
          alt={alt}
          onLoad={(e) => { readAspect(e.currentTarget); setShown((s) => (s && s.src === shown.src ? { ...s, loaded: true } : s)) }}
          onError={() => onError?.()}
          className={`absolute inset-0 w-full h-full object-contain ${outgoing ? "slide-swap-in" : "slide-reveal"}`}
          style={{ "--reveal-delay": revealDelay } as React.CSSProperties}
          data-loaded={shown.loaded}
          data-shown
        />
      )}

      {/* Newer image loading off-screen; swaps in once ready */}
      {incoming && (
        <img
          src={incoming}
          alt=""
          aria-hidden
          className="absolute inset-0 w-full h-full object-contain opacity-0 pointer-events-none"
          data-incoming
          onLoad={(e) => {
            readAspect(e.currentTarget)
            const next = incoming
            setOutgoing(shown?.src ?? null)
            setShown({ src: next, loaded: true })
            setGlow(true)
            setIncoming((cur) => (cur === next ? null : cur))
          }}
          onError={() => { setIncoming(null); onError?.() }}
        />
      )}
      </>
      )}

      {children}
    </div>
  )
}
