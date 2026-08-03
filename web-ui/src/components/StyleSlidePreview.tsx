// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleSlidePreview — Renders style HTML as per-slide cards with number rail.
 *
 * If the HTML contains `<div class="slide ...>` markers, each slide is rendered
 * in its own iframe card (1920×1080 scaled to container width).
 * Falls back to a single full-document iframe when no .slide markers are found.
 *
 * The split algorithm matches sdpmPaths.ts listStylesFromDir:
 * cut at each `<div class="slide` occurrence; last slide extends to `</body>` or EOF.
 */

"use client"

import { useCallback, useRef, useState } from "react"

// Slide native dimensions (CSS px at 100%)
const SLIDE_WIDTH = 1920
const SLIDE_HEIGHT = 1080

/**
 * Split style HTML into head + individual slide bodies.
 * Returns null if no `.slide` divs are found (fallback path).
 */
export function splitStyleSlides(html: string): { head: string; slides: string[] } | null {
  // Extract <head> content
  const headMatch = html.match(/<head[^>]*>([\s\S]*?)<\/head>/i)
  const head = headMatch ? headMatch[1] : ""

  // Find all `<div class="slide` positions
  const regex = /<div class="slide[\s"]/g
  const positions: number[] = []
  let m: RegExpExecArray | null
  while ((m = regex.exec(html)) !== null) {
    positions.push(m.index)
  }

  if (positions.length === 0) return null

  // Determine the end boundary (</body> or end of string)
  const bodyCloseIdx = html.indexOf("</body>")
  const endBoundary = bodyCloseIdx !== -1 ? bodyCloseIdx : html.length

  const slides: string[] = []
  for (let i = 0; i < positions.length; i++) {
    const start = positions[i]
    const end = i < positions.length - 1 ? positions[i + 1] : endBoundary
    let slice = html.slice(start, end)
    // Remove trailing </div> remnants (lone closing tags at the end)
    slice = slice.replace(/(<\/div>\s*)+$/, "")
    slides.push(slice)
  }

  return { head, slides }
}

/** Inject minimal reset into a single-slide HTML document. */
function prepareSlideDoc(head: string, slideBody: string): string {
  const reset = `<style data-preview-reset>
html,body{margin:0!important;padding:0!important;zoom:1!important;overflow:hidden!important}
.slide{margin:0 auto!important}
</style>`
  return `<!DOCTYPE html><html><head>${head}${reset}</head><body>${slideBody}</body></html>`
}

/**
 * Build a cover document from full style HTML — splits via splitStyleSlides
 * and returns the first slide with zoom reset. Falls back to the full HTML
 * when no .slide markers are found.
 */
export function buildCoverDoc(html: string): string {
  const split = splitStyleSlides(html)
  if (split) {
    return prepareSlideDoc(split.head, split.slides[0])
  }
  return html
}

/** Inject minimal reset into full style HTML (fallback path). */
function prepareHtml(html: string): string {
  const reset = `<style data-preview-reset>
html,body{margin:0!important;padding:0!important;zoom:1!important;overflow:visible!important}
.slide{margin:0 auto 8px!important}
</style>`
  if (html.includes("</head>")) {
    return html.replace("</head>", `${reset}</head>`)
  }
  return reset + html
}

function countSlides(html: string): number {
  const matches = html.match(/class="slide[\s"]/g)
  return matches ? matches.length : 1
}

/** Fallback: single iframe showing full document (existing behavior). */
function FallbackPreview({ html, containerWidth }: { html: string; containerWidth: number }) {
  const IFRAME_WIDTH = 2200
  const scale = containerWidth > 0 ? containerWidth / IFRAME_WIDTH : 0
  const slideCount = countSlides(html)
  const slideWithGap = SLIDE_HEIGHT + 8
  const totalHeight = (slideWithGap * slideCount) * scale

  if (scale <= 0) return null

  return (
    <div style={{ width: "100%", height: totalHeight, overflow: "hidden" }}>
      <iframe
        srcDoc={prepareHtml(html)}
        className="pointer-events-none"
        style={{
          width: IFRAME_WIDTH,
          height: slideWithGap * slideCount,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          border: "none",
        }}
        sandbox="allow-same-origin"
        title="Style Preview"
      />
    </div>
  )
}

/** Per-slide card with iframe scaled to the face column width. */
function SlideCard({ head, slideBody, index, faceWidth }: { head: string; slideBody: string; index: number; faceWidth: number }) {
  const scale = faceWidth / SLIDE_WIDTH
  const cardHeight = SLIDE_HEIGHT * scale

  return (
    <div
      className="grid gap-x-3.5"
      style={{ gridTemplateColumns: "36px 1fr" }}
    >
      {/* Number rail */}
      <span className="font-mono text-xs text-foreground-muted text-right pt-2 select-none" style={{ fontVariantNumeric: "tabular-nums" }}>
        {index + 1}
      </span>
      {/* Card */}
      <div className="rounded-[10px] border border-border-hover overflow-hidden shadow-[0_10px_32px_rgba(0,0,0,0.2)] transition-[transform,box-shadow] duration-[250ms] ease-out hover:-translate-y-[2px] hover:shadow-[0_16px_44px_rgba(0,0,0,0.26)] motion-reduce:hover:translate-y-0">
        <div style={{ width: "100%", height: cardHeight, overflow: "hidden" }}>
          <iframe
            srcDoc={prepareSlideDoc(head, slideBody)}
            className="pointer-events-none"
            style={{
              width: SLIDE_WIDTH,
              height: SLIDE_HEIGHT,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
              border: "none",
            }}
            sandbox="allow-same-origin"
            loading="lazy"
            title={`Slide ${index + 1}`}
          />
        </div>
      </div>
    </div>
  )
}

export function StyleSlidePreview({ html, loading }: { html: string; loading: boolean }) {
  const [containerWidth, setContainerWidth] = useState(0)
  const roRef = useRef<ResizeObserver | null>(null)
  const measuredRef = useCallback((node: HTMLDivElement | null) => {
    if (roRef.current) { roRef.current.disconnect(); roRef.current = null }
    if (node) {
      const w = node.getBoundingClientRect().width
      if (w > 0) setContainerWidth(w)
      roRef.current = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width))
      roRef.current.observe(node)
    }
  }, [])

  if (loading || !html) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
      </div>
    )
  }

  const split = splitStyleSlides(html)
  // Rail (36px) + gap (14px) — the slide face gets the remaining width
  const faceWidth = Math.max(containerWidth - 50, 0)

  return (
    <div ref={measuredRef} className="w-full max-w-4xl mx-auto">
      {containerWidth > 0 ? (
        split ? (
          /* Per-slide card view */
          <div className="flex flex-col" style={{ gap: "22px" }}>
            {split.slides.map((slide, i) => (
              <SlideCard
                key={i}
                head={split.head}
                slideBody={slide}
                index={i}
                faceWidth={faceWidth}
              />
            ))}
          </div>
        ) : (
          /* Fallback: single iframe */
          <FallbackPreview html={html} containerWidth={containerWidth} />
        )
      ) : (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
        </div>
      )}
    </div>
  )
}
