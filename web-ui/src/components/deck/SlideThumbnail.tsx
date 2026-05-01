// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlideThumbnail — Skeleton → reveal transition for a single slide preview.
 *
 * Shows a shimmer skeleton placeholder at 16:9 aspect ratio until the image
 * loads, then reveals with a staggered scale+fade animation. On src change
 * (measure/generate update), resets to skeleton to maintain layout height
 * and prevent scroll position shifts.
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
  children?: React.ReactNode
}

export function SlideThumbnail({ src, alt, index, onClick, className, updated, slug, children }: SlideThumbnailProps) {
  const [loaded, setLoaded] = useState(false)
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
      className={`aspect-[16/9] relative overflow-hidden rounded-lg ${updated ? "slide-updated" : ""} ${className || ""}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick() } } : undefined}
      data-slide-id={slug}
    >
      {/* Skeleton layer */}
      {!loaded && <div className="slide-skeleton absolute inset-0" />}

      {/* Image layer */}
      {src && (
        <img
          src={src}
          alt={alt}
          onLoad={() => setLoaded(true)}
          className="absolute inset-0 w-full h-full object-cover slide-reveal"
          style={{ "--reveal-delay": `${index * 60}ms` } as React.CSSProperties}
          data-loaded={loaded}
        />
      )}

      {children}
    </div>
  )
}
