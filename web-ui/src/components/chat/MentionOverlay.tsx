// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * MentionOverlay — Renders a transparent overlay on top of a textarea
 * that highlights @Page N and @DeckName mentions with color and shows
 * a PNG preview tooltip on hover.
 *
 * Replaces the former SlideTagOverlay ([Slide:PageN] format).
 */

"use client"

import { RefObject, useState, useEffect } from "react"
import { createPortal } from "react-dom"

/** Regex to match @DeckName(#id):Page N or @DeckName(#id) or @[DeckName] or @Page N */
const ALL_MENTIONS_RE = /@([^@(]+)\(#([^)]+)\):Page\s(\d+)|@([^@(]+)\(#([^)]+)\)|@\[([^\]]+)\]|@Page\s(\d+)/g

interface MentionOverlayProps {
  /** Current textarea value. */
  text: string
  /** Ref to the textarea element for scroll sync. */
  textareaRef: RefObject<HTMLTextAreaElement | null>
  /** Ordered array of slide preview URLs (index 0 = Page 1). */
  slidePreviewUrls?: (string | null)[]
  /** Map of deck name to thumbnail URL for deck mentions. */
  deckThumbnails?: Record<string, string>
}

interface HoveredMention {
  type: "slide" | "deck"
  page?: number
  deckName?: string
  x: number
  y: number
}

/**
 * Overlay that mirrors textarea text, highlighting @mentions.
 * Positioned absolutely over the textarea with pointer-events-none,
 * except on the mention spans which capture hover.
 *
 * @param props - MentionOverlayProps
 */
export function MentionOverlay({ text, textareaRef, slidePreviewUrls, deckThumbnails }: MentionOverlayProps) {
  const [scrollTop, setScrollTop] = useState(0)
  const [hovered, setHovered] = useState<HoveredMention | null>(null)

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    const onScroll = () => setScrollTop(ta.scrollTop)
    ta.addEventListener("scroll", onScroll)
    return () => ta.removeEventListener("scroll", onScroll)
  }, [textareaRef])

  // Build segments: alternating plain text and mentions
  const segments: { text: string; type?: "slide" | "deck"; page?: number; deckName?: string }[] = []
  let lastIndex = 0
  const re = new RegExp(ALL_MENTIONS_RE)
  let match: RegExpExecArray | null

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) })
    }

    if (match[1]) {
      // @DeckName(#id):Page N — slide with deckId
      segments.push({ text: match[0], type: "slide", page: parseInt(match[3], 10), deckName: match[1] })
    } else if (match[4]) {
      // @DeckName(#id) — deck reference
      segments.push({ text: match[0], type: "deck", deckName: match[4] })
    } else if (match[6]) {
      // @[DeckName] — legacy deck
      segments.push({ text: match[0], type: "deck", deckName: match[6] })
    } else if (match[7]) {
      // @Page N — legacy slide
      segments.push({ text: match[0], type: "slide", page: parseInt(match[7], 10) })
    }

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
  const getSlidePreview = (page: number): string | null => {
    if (!slidePreviewUrls || page < 1 || page > slidePreviewUrls.length) return null
    return slidePreviewUrls[page - 1]
  }

  /**
   * Get the thumbnail URL for a deck name.
   *
   * @param name - Deck name
   * @returns Thumbnail URL or null
   */
  const getDeckThumbnail = (name: string): string | null => {
    return deckThumbnails?.[name] || null
  }

  const previewUrl = hovered?.type === "slide" && hovered.page
    ? getSlidePreview(hovered.page)
    : hovered?.type === "deck" && hovered.deckName
      ? getDeckThumbnail(hovered.deckName)
      : null

  return (
    <>
      <div
        aria-hidden="true"
        className="absolute inset-0 py-1 pr-2 text-[13px] leading-relaxed whitespace-pre-wrap break-words overflow-hidden pointer-events-none font-[inherit] tracking-[inherit] z-10"
      >
        <div style={{ marginTop: `-${scrollTop}px` }}>
        {segments.map((seg, i) =>
          seg.type ? (
            <span
              key={i}
              className="text-blue-400 font-medium pointer-events-auto cursor-default relative z-20"
              onMouseEnter={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                setHovered({
                  type: seg.type!,
                  page: seg.page,
                  deckName: seg.deckName,
                  x: rect.left,
                  y: rect.top,
                })
              }}
              onMouseLeave={() => setHovered(null)}
            >
              {seg.text}
            </span>
          ) : (
            <span key={i} className="text-foreground">{seg.text}</span>
          ),
        )}
        </div>
      </div>

      {/* Tooltip with preview — portaled to body to escape overflow-hidden */}
      {hovered && previewUrl && createPortal(
        <div
          className="fixed z-[9999] rounded-lg overflow-hidden slide-shadow"
          style={{
            left: hovered.x,
            top: hovered.y - 8,
            transform: "translateY(-100%)",
            maxWidth: "280px",
          }}
        >
          <img
            src={previewUrl}
            alt={
              hovered.type === "slide"
                ? `Slide ${hovered.page} preview`
                : `${hovered.deckName} thumbnail`
            }
            className="w-full"
          />
        </div>,
        document.body,
      )}
    </>
  )
}
