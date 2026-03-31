// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SlideTagOverlay — Renders a transparent overlay on top of a textarea
 * that highlights [Slide:PageN] tags with color and shows a PNG preview
 * tooltip on hover.
 */

"use client"

import { RefObject, useState, useEffect } from "react"

/** Regex to match [Slide:PageN] tags in text. */
const SLIDE_TAG_RE = /\[Slide:Page(\d+)\]/g

interface SlideTagOverlayProps {
  /** Current textarea value. */
  text: string
  /** Ref to the textarea element for scroll sync. */
  textareaRef: RefObject<HTMLTextAreaElement | null>
  /** Ordered array of slide preview URLs (index 0 = Page 1). */
  slidePreviewUrls?: (string | null)[]
}

/**
 * Overlay that mirrors textarea text, highlighting slide tags.
 * Positioned absolutely over the textarea with pointer-events-none,
 * except on the tag spans which capture hover.
 */
export function SlideTagOverlay({ text, textareaRef, slidePreviewUrls }: SlideTagOverlayProps) {
  const [scrollTop, setScrollTop] = useState(0)
  const [hoveredTag, setHoveredTag] = useState<{ page: number; x: number; y: number } | null>(null)

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    const onScroll = () => setScrollTop(ta.scrollTop)
    ta.addEventListener("scroll", onScroll)
    return () => ta.removeEventListener("scroll", onScroll)
  }, [textareaRef])

  // Build segments: alternating plain text and slide tags
  const segments: { text: string; page?: number }[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  const re = new RegExp(SLIDE_TAG_RE)
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) })
    }
    segments.push({ text: match[0], page: parseInt(match[1], 10) })
    lastIndex = re.lastIndex
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) })
  }

  /**
   * Get the preview URL for a 1-based page number.
   *
   * @param page - 1-based slide page number
   * @returns Preview URL or null
   */
  const getPreviewUrl = (page: number): string | null => {
    if (!slidePreviewUrls || page < 1 || page > slidePreviewUrls.length) return null
    return slidePreviewUrls[page - 1]
  }

  return (
    <>
      <div
        aria-hidden="true"
        className="absolute inset-0 py-1.5 text-sm whitespace-pre-wrap break-words overflow-hidden pointer-events-none"
        style={{ transform: `translateY(-${scrollTop}px)` }}
      >
        {segments.map((seg, i) =>
          seg.page != null ? (
            <span
              key={i}
              className="text-blue-400 font-medium pointer-events-auto cursor-default"
              onMouseEnter={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                setHoveredTag({ page: seg.page!, x: rect.left, y: rect.top })
              }}
              onMouseLeave={() => setHoveredTag(null)}
            >
              {seg.text}
            </span>
          ) : (
            <span key={i} className="text-foreground">{seg.text}</span>
          )
        )}
      </div>

      {/* Tooltip with PNG preview */}
      {hoveredTag && getPreviewUrl(hoveredTag.page) && (
        <div
          className="fixed z-50 rounded-lg overflow-hidden slide-shadow"
          style={{
            left: hoveredTag.x,
            top: hoveredTag.y - 8,
            transform: "translateY(-100%)",
            maxWidth: "280px",
          }}
        >
          <img
            src={getPreviewUrl(hoveredTag.page)!}
            alt={`Slide ${hoveredTag.page} preview`}
            className="w-full"
          />
        </div>
      )}
    </>
  )
}
