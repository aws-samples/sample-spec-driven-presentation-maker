// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleSlidePreview — Renders full style HTML scaled to container width.
 *
 * Style HTMLs have `body { zoom: 0.7; padding: 40px }` for standalone browser
 * viewing. We reset only zoom/padding/margin/background on body so the slides
 * render at their natural 1920×1080 size. Border/outline on .slide is preserved
 * as it's part of the design.
 *
 * The iframe is sized wider than 1920 to accommodate border/outline overflow,
 * and CSS transform scales it to fit the container.
 */

"use client"

import { useCallback, useRef, useState } from "react"

// Extra width to accommodate border + outline on .slide (e.g. border 56px + outline 40px each side)
const IFRAME_WIDTH = 2200
const SLIDE_HEIGHT = 1080

/** Inject minimal reset into style HTML. Only neutralize body-level layout, not slide decoration. */
function prepareHtml(html: string): string {
  const reset = `<style data-preview-reset>
html,body{margin:0!important;padding:0!important;background:transparent!important;zoom:1!important;overflow:visible!important}
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

  const scale = containerWidth > 0 ? containerWidth / IFRAME_WIDTH : 0
  const slideCount = countSlides(html)
  const slideWithGap = SLIDE_HEIGHT + 8
  const totalHeight = (slideWithGap * slideCount) * scale

  return (
    <div ref={measuredRef} className="w-full">
      {scale > 0 ? (
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
      ) : (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
        </div>
      )}
    </div>
  )
}
