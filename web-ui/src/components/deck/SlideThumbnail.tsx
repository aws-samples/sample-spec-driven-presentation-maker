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
 */

"use client"

import { useState, useEffect, useRef } from "react"

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
  children?: React.ReactNode
}

export function SlideThumbnail({ src, alt, index, onClick, className, updated, slug, onAspectRatio, onError, children }: SlideThumbnailProps) {
  const [loaded, setLoaded] = useState(false)
  const [aspectRatio, setAspectRatio] = useState<string>("16/9")
  const prevSrc = useRef(src)

  // Reset loaded state when src changes (triggers skeleton re-display)
  useEffect(() => {
    if (src !== prevSrc.current) {
      setLoaded(false)
      prevSrc.current = src
    }
  }, [src])

  return (
    <div
      className={`relative overflow-hidden rounded-lg ${updated ? "slide-updated" : ""} ${className || ""}`}
      style={{ aspectRatio }}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick() } } : undefined}
      data-slide-id={slug}
    >
      {/* Skeleton layer — shown only while loading an actual src */}
      {!loaded && src && <div className="slide-skeleton absolute inset-0" />}

      {/* Explicit placeholder when no src is available */}
      {!src && (
        <div className="absolute inset-0 flex items-center justify-center bg-muted/30" data-placeholder>
          <span className="text-xs text-muted-foreground">Preview unavailable</span>
        </div>
      )}

      {/* Image layer */}
      {src && (
        <img
          src={src}
          alt={alt}
          onLoad={(e) => {
            const img = e.currentTarget
            if (img.naturalWidth > 0 && img.naturalHeight > 0) {
              setAspectRatio(`${img.naturalWidth}/${img.naturalHeight}`)
              onAspectRatio?.(img.naturalWidth / img.naturalHeight)
            }
            setLoaded(true)
          }}
          onError={() => onError?.()}
          className="absolute inset-0 w-full h-full object-contain slide-reveal"
          style={{ "--reveal-delay": `${index * 60}ms` } as React.CSSProperties}
          data-loaded={loaded}
        />
      )}

      {children}
    </div>
  )
}
