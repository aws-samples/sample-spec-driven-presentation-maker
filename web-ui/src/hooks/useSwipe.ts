// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useSwipe — Detects horizontal swipe gestures on touch devices.
 * Ignores vertical scrolling (when vertical movement exceeds horizontal).
 *
 * @param onSwipeLeft - Callback for left swipe
 * @param onSwipeRight - Callback for right swipe
 * @param threshold - Minimum horizontal distance in px (default 50)
 * @returns Ref to attach to the swipeable container element
 */

import { useRef, useEffect, RefObject } from "react"

export function useSwipe(
  onSwipeLeft: () => void,
  onSwipeRight: () => void,
  threshold: number = 50,
): RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null)
  const startX = useRef(0)
  const startY = useRef(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const onTouchStart = (e: TouchEvent) => {
      startX.current = e.touches[0].clientX
      startY.current = e.touches[0].clientY
    }

    const onTouchEnd = (e: TouchEvent) => {
      const dx = e.changedTouches[0].clientX - startX.current
      const dy = e.changedTouches[0].clientY - startY.current

      // Ignore if vertical movement is dominant
      if (Math.abs(dy) > Math.abs(dx)) return

      if (dx < -threshold) onSwipeLeft()
      if (dx > threshold) onSwipeRight()
    }

    el.addEventListener("touchstart", onTouchStart, { passive: true })
    el.addEventListener("touchend", onTouchEnd, { passive: true })
    return () => {
      el.removeEventListener("touchstart", onTouchStart)
      el.removeEventListener("touchend", onTouchEnd)
    }
  }, [onSwipeLeft, onSwipeRight, threshold])

  return ref
}
