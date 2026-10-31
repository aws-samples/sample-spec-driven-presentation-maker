// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewSlideLayer — the comment overlay on one slide of the full view.
 *
 * Rendered as a sibling of the slide preview (outside `.slide-cv`, whose content-visibility
 * clips children, so frame tags can sit above the slide's top edge). With the tool off the
 * layer lets the pointer through and only the frames take it; with the tool on, the slide
 * background draws (drag) or places (click) frames, following `resolveBackgroundRelease`:
 * a click while something is open or selected only confirms it.
 *
 * Drafts: body drag moves, the 8 handles of the selected draft resize, a click opens the card.
 * Sent open comments: read-only, pulse while the agent works on them. Done comments are not drawn.
 */

"use client"

import { useLayoutEffect, useRef, useState } from "react"
import type { PointerEvent as ReactPointerEvent } from "react"
import { useTranslations } from "next-intl"
import { Loader2 } from "lucide-react"
import { useReview } from "@/components/review/ReviewProvider"
import {
  HANDLES, clickFrame, moveRect, normalizeDrag, pointToSlide, resizeRect, toPercent, withMinSize,
  type Handle, type Point, type Rect, type SlideSize,
} from "@/lib/review/geometry"
import { exceedsClickTolerance, exceedsFrameDragTolerance, resolveBackgroundRelease } from "@/lib/review/interaction"

type Drag =
  | { kind: "new"; p0: Point; p1: Point; moved: boolean; editingAtDown: boolean }
  | { kind: "move" | "resize"; handle?: Handle; name: string; p0: Point; origin: Rect; rect: Rect | null; moved: boolean; wasOpen: boolean }

interface ReviewSlideLayerProps {
  slug: string
  /** Position of the slide in the deck (0-based). */
  index: number
}

export function ReviewSlideLayer({ slug, index }: ReviewSlideLayerProps) {
  const review = useReview()
  const t = useTranslations("review")
  const layerRef = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const [temp, setTemp] = useState<Rect | null>(null)
  const [live, setLive] = useState<{ name: string; rect: Rect } | null>(null)

  // The open card follows a frame while it is dragged.
  const notifyFrameMoved = review?.notifyFrameMoved
  useLayoutEffect(() => { if (live) notifyFrameMoved?.() }, [live, notifyFrameMoved])

  if (!review || !review.enabled) return null
  const size = review.slideSize

  const toSlide = (e: ReactPointerEvent): Point => {
    const box = layerRef.current?.getBoundingClientRect() ?? { left: 0, top: 0, width: 0, height: 0 }
    return pointToSlide(e.clientX, e.clientY, box, size)
  }
  const capture = (e: ReactPointerEvent) => {
    try { (e.currentTarget as Element).setPointerCapture(e.pointerId) } catch { /* not supported */ }
  }

  const onBackgroundDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || e.target !== e.currentTarget) return
    // Something open or selected at the press: a click only confirms it (R2.1).
    const editingAtDown = !!review.editor || !!review.selected
    review.closeEditor(true)
    if (!review.toolOn) { review.select(null); return }
    const p0 = toSlide(e)
    drag.current = { kind: "new", p0, p1: p0, moved: false, editingAtDown }
    capture(e)
  }

  const onFrameDown = (e: ReactPointerEvent<HTMLElement>, key: string, kind: "draft" | "sent", handle?: Handle) => {
    e.stopPropagation()
    if (e.button !== 0) return
    const wasOpen = review.editor?.key === key
    if (!wasOpen) review.closeEditor(true)
    review.select(key)
    if (kind === "sent") { review.openEditor(key); return }
    const frame = review.drafts.find(d => d.name === key)
    if (!frame) return
    drag.current = { kind: handle ? "resize" : "move", handle, name: key, p0: toSlide(e), origin: frame.rect, rect: null, moved: false, wasOpen }
    review.setDragging(true)
    capture(e)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const p = toSlide(e)
    if (d.kind === "new") {
      d.p1 = p
      if (!d.moved && exceedsClickTolerance(d.p0, p, size)) d.moved = true
      if (d.moved) setTemp(normalizeDrag(d.p0, p))
      return
    }
    const dx = p[0] - d.p0[0]
    const dy = p[1] - d.p0[1]
    if (!d.moved && exceedsFrameDragTolerance(dx, dy, size)) {
      d.moved = true
      if (!d.wasOpen) review.setPeek(null)
    }
    if (!d.moved) return
    d.rect = d.kind === "move" ? moveRect(d.origin, dx, dy, size) : resizeRect(d.origin, d.handle!, dx, dy, size)
    setLive({ name: d.name, rect: d.rect })
  }

  const finish = (cancelled: boolean) => {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.kind === "new") {
      setTemp(null)
      if (cancelled) return
      const action = resolveBackgroundRelease({ moved: d.moved, editingAtDown: d.editingAtDown })
      if (action === "confirm") { review.select(null); return }
      const rect = action === "place" ? clickFrame(d.p0, size) : withMinSize(normalizeDrag(d.p0, d.p1), size)
      review.addFrame(slug, rect)
      return
    }
    review.setDragging(false)
    setLive(null)
    if (cancelled) return
    if (d.moved && d.rect) review.updateRect(d.name, d.rect)
    if (d.wasOpen) review.notifyFrameMoved() // the editor stayed open: it follows the frame
    else if (!d.moved) review.openEditor(d.name) // a click turns the hover card into the card in place
  }

  const drafts = review.drafts.filter(d => d.slide === slug)
  const sent = review.openSent.filter(f => f.slide === slug)

  return (
    <div
      ref={layerRef}
      data-review-layer={slug}
      data-slide-index={index}
      className={`absolute inset-0 z-10 rounded-lg ${review.toolOn ? "cursor-crosshair" : ""}`}
      style={{ pointerEvents: review.toolOn ? "auto" : "none", touchAction: review.toolOn ? "none" : undefined }}
      onPointerDown={onBackgroundDown}
      onPointerMove={onPointerMove}
      onPointerUp={() => finish(false)}
      onPointerCancel={() => finish(true)}
    >
      {drafts.map((d) => {
        const rect = live?.name === d.name ? live.rect : d.rect
        const selected = review.selected === d.name
        return (
          <FrameBox
            key={d.name}
            frameKey={d.name}
            name={d.name}
            kind="draft"
            rect={rect}
            size={size}
            selected={selected}
            highlight={review.highlight === d.name}
            working={false}
            label={t("frameLabel", { name: d.name })}
            onPointerDown={(e, handle) => onFrameDown(e, d.name, "draft", handle)}
            onOpen={() => review.openEditor(d.name)}
            handles={selected}
          />
        )
      })}
      {sent.map((f) => (
        <FrameBox
          key={f.key}
          frameKey={f.key}
          name={f.name}
          kind="sent"
          rect={f.rect}
          size={f.size}
          selected={review.selected === f.key}
          highlight={review.highlight === f.key}
          working
          label={t("frameLabel", { name: f.name })}
          onPointerDown={(e) => onFrameDown(e, f.key, "sent")}
          onOpen={() => review.openEditor(f.key)}
          handles={false}
        />
      ))}
      {temp && <div className="review-temp" style={toPercent(temp, size)} data-review-temp />}
    </div>
  )
}

interface FrameBoxProps {
  frameKey: string
  name: string
  kind: "draft" | "sent"
  rect: Rect
  size: SlideSize
  selected: boolean
  highlight: boolean
  working: boolean
  label: string
  handles: boolean
  onPointerDown: (e: ReactPointerEvent<HTMLElement>, handle?: Handle) => void
  onOpen: () => void
}

function FrameBox({ frameKey, name, kind, rect, size, selected, highlight, working, label, handles, onPointerDown, onOpen }: FrameBoxProps) {
  return (
    <div
      className="review-frame"
      data-review-frame={frameKey}
      data-kind={kind}
      data-selected={selected}
      data-highlight={highlight}
      data-working={working}
      style={toPercent(rect, size)}
      role="button"
      tabIndex={0}
      aria-label={label}
      onPointerDown={(e) => onPointerDown(e)}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onOpen() } }}
    >
      <div className="review-tag text-xs font-bold">
        {working && <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden />}
        {name}
      </div>
      {handles && HANDLES.map((h) => (
        <div key={h} className={`review-hd review-hd-${h}`} data-handle={h} onPointerDown={(e) => { e.stopPropagation(); onPointerDown(e, h) }} />
      ))}
    </div>
  )
}
