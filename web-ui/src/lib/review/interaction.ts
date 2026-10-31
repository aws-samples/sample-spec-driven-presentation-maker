// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Pointer rules for the comment tool (requirements R2.1 / R2.2).
 *
 * A press on the slide background that ends without moving is a click. When a frame was
 * being edited or was selected at the moment of the press, that click only confirms it
 * (closes the card, clears the selection); when nothing was, the click places a new frame.
 * A press that moves beyond the tolerance draws a frame.
 */

import type { Point, SlideSize } from "@/lib/review/geometry"

/** Movement (fraction of the slide side) below which a background press counts as a click. */
export const CLICK_TOLERANCE_FRACTION = 0.012
/** Movement (fraction of the slide side, |dx| + |dy|) below which a press on a frame is a click. */
export const FRAME_DRAG_TOLERANCE_FRACTION = 0.004

export type BackgroundRelease = "draw" | "confirm" | "place"

export function resolveBackgroundRelease({ moved, editingAtDown }: { moved: boolean; editingAtDown: boolean }): BackgroundRelease {
  if (moved) return "draw"
  return editingAtDown ? "confirm" : "place"
}

/** Whether a background press from `p0` to `p1` has left the click tolerance. */
export function exceedsClickTolerance([x0, y0]: Point, [x1, y1]: Point, size: SlideSize): boolean {
  return Math.abs(x1 - x0) > size.width * CLICK_TOLERANCE_FRACTION
    || Math.abs(y1 - y0) > size.height * CLICK_TOLERANCE_FRACTION
}

/** Whether a press on a frame moved by (dx, dy) slide px is a drag rather than a click. */
export function exceedsFrameDragTolerance(dx: number, dy: number, size: SlideSize): boolean {
  return Math.abs(dx) / size.width + Math.abs(dy) / size.height > FRAME_DRAG_TOLERANCE_FRACTION
}

/** Whether keyboard focus is in a text field, where the tool's shortcuts must not fire. */
export function isTypingTarget(el: Element | null): boolean {
  if (!el) return false
  const tag = el.tagName
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true
  return (el as HTMLElement).isContentEditable === true || el.closest("[contenteditable=''],[contenteditable='true']") !== null
}
