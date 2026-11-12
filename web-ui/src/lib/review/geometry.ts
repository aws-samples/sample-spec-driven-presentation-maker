// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Frame geometry for the comment tool. Every rect is `[x, y, w, h]` in slide px (the deck's
 * `slideSize`), the unit the review file and the slide files use; the overlay converts to
 * percentages only for drawing.
 */

import type { ReviewRect } from "@/lib/review/schema"

export type Rect = ReviewRect
export type Point = [number, number]
export interface SlideSize { width: number; height: number }

export const DEFAULT_SIZE: SlideSize = { width: 1920, height: 1080 }
/** Smallest frame side, as a fraction of the slide side. */
export const MIN_FRAME_FRACTION = 0.02
/** A click places a frame this big (fractions of the slide), centred on the pointer. */
export const CLICK_FRAME_FRACTION = { width: 0.09, height: 0.16 } as const

export type Handle = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw"
export const HANDLES: readonly Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"]

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const minW = (size: SlideSize) => size.width * MIN_FRAME_FRACTION
const minH = (size: SlideSize) => size.height * MIN_FRAME_FRACTION

/** CSS position of `rect` as percentages of the slide. */
export function toPercent([x, y, w, h]: Rect, size: SlideSize): { left: string; top: string; width: string; height: string } {
  const pct = (v: number, total: number) => `${total > 0 ? (v / total) * 100 : 0}%`
  return { left: pct(x, size.width), top: pct(y, size.height), width: pct(w, size.width), height: pct(h, size.height) }
}

/** Slide px under a pointer, clamped to the slide. `box` is the slide's on-screen rect. */
export function pointToSlide(
  clientX: number, clientY: number,
  box: { left: number; top: number; width: number; height: number }, size: SlideSize,
): Point {
  const x = box.width > 0 ? ((clientX - box.left) / box.width) * size.width : 0
  const y = box.height > 0 ? ((clientY - box.top) / box.height) * size.height : 0
  return [clamp(x, 0, size.width), clamp(y, 0, size.height)]
}

/** Rect spanned by a drag from `p0` to `p1`, in either direction. */
export function normalizeDrag([x0, y0]: Point, [x1, y1]: Point): Rect {
  return [Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0)]
}

/** Grow `rect` to the minimum frame size, keeping it inside the slide. */
export function withMinSize([x, y, w, h]: Rect, size: SlideSize): Rect {
  const nw = Math.min(size.width, Math.max(minW(size), w))
  const nh = Math.min(size.height, Math.max(minH(size), h))
  return [clamp(x, 0, size.width - nw), clamp(y, 0, size.height - nh), nw, nh]
}

/** The frame a click places: a fixed share of the slide, centred on `point`, inside the slide. */
export function clickFrame([px, py]: Point, size: SlideSize): Rect {
  const w = size.width * CLICK_FRAME_FRACTION.width
  const h = size.height * CLICK_FRAME_FRACTION.height
  return [clamp(px - w / 2, 0, size.width - w), clamp(py - h / 2, 0, size.height - h), w, h]
}

/** `rect` moved by (dx, dy), kept inside the slide. */
export function moveRect([x, y, w, h]: Rect, dx: number, dy: number, size: SlideSize): Rect {
  return [clamp(x + dx, 0, size.width - w), clamp(y + dy, 0, size.height - h), w, h]
}

/** `rect` resized from `handle` by (dx, dy): the opposite edges stay, sides never drop below the minimum. */
export function resizeRect(rect: Rect, handle: Handle, dx: number, dy: number, size: SlideSize): Rect {
  const [ox, oy, ow, oh] = rect
  let [x, y, w, h] = rect
  if (handle.includes("e")) w = Math.max(minW(size), Math.min(size.width - ox, ow + dx))
  if (handle.includes("s")) h = Math.max(minH(size), Math.min(size.height - oy, oh + dy))
  if (handle.includes("w")) { x = clamp(ox + dx, 0, ox + ow - minW(size)); w = ow + (ox - x) }
  if (handle.includes("n")) { y = clamp(oy + dy, 0, oy + oh - minH(size)); h = oh + (oy - y) }
  return [x, y, w, h]
}

/** Integer rect inside the slide (what the review file stores): x, y ≥ 0, w, h ≥ 1, x + w ≤ W, y + h ≤ H. */
export function roundRect([x, y, w, h]: Rect, size: SlideSize): Rect {
  const W = Math.max(1, Math.floor(size.width))
  const H = Math.max(1, Math.floor(size.height))
  const rx = clamp(Math.round(x), 0, W - 1)
  const ry = clamp(Math.round(y), 0, H - 1)
  return [rx, ry, clamp(Math.round(w), 1, W - rx), clamp(Math.round(h), 1, H - ry)]
}
