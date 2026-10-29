// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * HtmlSlideFrame — Static thumbnail of one HTML slide (`preview/<slug>.html`).
 *
 * The slide renders at its canvas size in a fully sandboxed iframe (`sandbox=""`:
 * no scripts, opaque origin) and is scaled to the container with a CSS
 * transform, measured by a ResizeObserver (StyleSlidePreview pattern). The
 * iframe is inert (no pointer events, not focusable, hidden from assistive
 * technology); the wrapper carries the accessible label and fills its
 * positioned parent (`absolute inset-0`).
 */

"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { previewIdentity } from "@/lib/preview"

interface HtmlSlideFrameProps {
  src: string
  /** Accessible label of the thumbnail. */
  title: string
  /** Canvas size in CSS px. */
  width?: number
  height?: number
  /** "contain" shows the whole slide; "cover" fills the box and crops the overflow. */
  fit?: "contain" | "cover"
  className?: string
  onLoad?: () => void
}

export function HtmlSlideFrame({ src, title, width = 1920, height = 1080, fit = "contain", className, onLoad }: HtmlSlideFrameProps) {
  const [box, setBox] = useState({ w: 0, h: 0 })
  const roRef = useRef<ResizeObserver | null>(null)
  const measuredRef = useCallback((node: HTMLDivElement | null) => {
    if (roRef.current) { roRef.current.disconnect(); roRef.current = null }
    if (!node) return
    const rect = node.getBoundingClientRect()
    if (rect.width > 0) setBox({ w: rect.width, h: rect.height })
    roRef.current = new ResizeObserver(([entry]) => setBox({ w: entry.contentRect.width, h: entry.contentRect.height }))
    roRef.current.observe(node)
  }, [])
  useEffect(() => () => roRef.current?.disconnect(), [])

  // Cloud URLs are re-signed on every poll: keep the loaded document until the
  // file itself changes, so a fresh signature never reloads the frame.
  const [shownSrc, setShownSrc] = useState(src)
  useEffect(() => {
    setShownSrc((current) => (previewIdentity(current) === previewIdentity(src) ? current : src))
  }, [src])

  const sx = box.w / width
  const sy = box.h > 0 ? box.h / height : sx
  const scale = fit === "cover" ? Math.max(sx, sy) : Math.min(sx, sy)
  const left = (box.w - width * scale) / 2
  const top = box.h > 0 ? (box.h - height * scale) / 2 : 0

  return (
    <div ref={measuredRef} role="img" aria-label={title} className={`absolute inset-0 overflow-hidden ${className ?? ""}`}>
      {/* Rendered before the first measurement too (scale 0 = invisible), so loading starts at once. */}
      <iframe
        src={shownSrc}
        title={title}
        sandbox=""
        referrerPolicy="no-referrer"
        loading="lazy"
        aria-hidden="true"
        tabIndex={-1}
        onLoad={onLoad}
        className="pointer-events-none absolute border-0"
        style={{
          width,
          height,
          left,
          top,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
        }}
      />
    </div>
  )
}
