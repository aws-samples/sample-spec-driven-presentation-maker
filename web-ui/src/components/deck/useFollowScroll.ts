// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useCallback, useEffect, useRef, type RefObject } from "react"

const REARM_MS = 3000
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
])

/** Follow compose changes until the user manually navigates the slide scroller. */
export function useFollowScroll(containerRef: RefObject<HTMLDivElement | null>) {
  const followRef = useRef(true)
  const rearmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const pause = () => { followRef.current = false }
    const pauseForKey = (event: KeyboardEvent) => {
      if (SCROLL_KEYS.has(event.key)) pause()
    }
    container.addEventListener("wheel", pause, { passive: true })
    container.addEventListener("touchmove", pause, { passive: true })
    container.addEventListener("keydown", pauseForKey)
    return () => {
      container.removeEventListener("wheel", pause)
      container.removeEventListener("touchmove", pause)
      container.removeEventListener("keydown", pauseForKey)
    }
  })

  useEffect(() => () => {
    if (rearmTimerRef.current) clearTimeout(rearmTimerRef.current)
  }, [])

  return useCallback((slug: string) => {
    if (rearmTimerRef.current) clearTimeout(rearmTimerRef.current)
    rearmTimerRef.current = setTimeout(() => {
      followRef.current = true
      rearmTimerRef.current = null
    }, REARM_MS)

    const container = containerRef.current
    if (!followRef.current || !container) return
    const css = (globalThis as typeof globalThis & { CSS?: { escape?: (value: string) => string } }).CSS
    const escapedSlug = css?.escape ? css.escape(slug) : slug.replaceAll('"', '\\"')
    const element = container.querySelector<HTMLElement>(`[data-slide-id="${escapedSlug}"]`)
    if (!element) return
    const elementRect = element.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    const offset = elementRect.top - containerRect.top + container.scrollTop - 24
    container.scrollTo({ top: offset, behavior: "smooth" })
  }, [containerRef])
}
