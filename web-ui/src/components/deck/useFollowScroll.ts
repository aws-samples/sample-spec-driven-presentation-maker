// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useCallback, useEffect, useRef } from "react"

const REARM_MS = 3000
const PROGRAMMATIC_SCROLL_WINDOW_MS = 600
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
  "Spacebar",
])

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof Element)) return false
  return Boolean(target.closest("input, textarea, select, [contenteditable]:not([contenteditable='false'])"))
}

/** Follow compose changes until the user manually navigates the slide scroller. */
export function useFollowScroll(container: HTMLDivElement | null) {
  const followRef = useRef(true)
  const lastManualAtRef = useRef(Number.NEGATIVE_INFINITY)
  const lastChangeAtRef = useRef(Number.NEGATIVE_INFINITY)
  const programmaticScrollRef = useRef(false)
  const programmaticTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearProgrammaticScroll = useCallback(() => {
    programmaticScrollRef.current = false
    if (programmaticTimerRef.current) clearTimeout(programmaticTimerRef.current)
    programmaticTimerRef.current = null
  }, [])

  const pause = useCallback(() => {
    followRef.current = false
    lastManualAtRef.current = Date.now()
    clearProgrammaticScroll()
  }, [clearProgrammaticScroll])

  useEffect(() => {
    if (!container) return
    const pauseForKey = (event: KeyboardEvent) => {
      if (SCROLL_KEYS.has(event.key) && !isEditableTarget(event.target)) pause()
    }
    const pauseForScroll = () => {
      if (!programmaticScrollRef.current) pause()
    }
    const pauseForPointer = (event: Event) => {
      if (!isEditableTarget(event.target)) pause()
    }
    container.addEventListener("wheel", pauseForPointer, { passive: true })
    container.addEventListener("touchmove", pauseForPointer, { passive: true })
    container.addEventListener("scroll", pauseForScroll, { passive: true })
    container.addEventListener("scrollend", clearProgrammaticScroll)
    document.addEventListener("keydown", pauseForKey, true)
    return () => {
      container.removeEventListener("wheel", pauseForPointer)
      container.removeEventListener("touchmove", pauseForPointer)
      container.removeEventListener("scroll", pauseForScroll)
      container.removeEventListener("scrollend", clearProgrammaticScroll)
      document.removeEventListener("keydown", pauseForKey, true)
      clearProgrammaticScroll()
    }
  }, [clearProgrammaticScroll, container, pause])

  return useCallback((slug: string) => {
    const now = Date.now()
    const previousChangeAt = lastChangeAtRef.current
    const isNewChange = now > previousChangeAt
    lastChangeAtRef.current = now
    if (
      !followRef.current
      && isNewChange
      && now - lastManualAtRef.current >= REARM_MS
      && now - previousChangeAt >= REARM_MS
    ) {
      followRef.current = true
    }
    if (!followRef.current || !container) return
    const css = (globalThis as typeof globalThis & { CSS?: { escape?: (value: string) => string } }).CSS
    const escapedSlug = css?.escape ? css.escape(slug) : slug.replaceAll('"', '\\"')
    const element = container.querySelector<HTMLElement>(`[data-slide-id="${escapedSlug}"]`)
    if (!element) return
    const elementRect = element.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    const offset = elementRect.top - containerRect.top + container.scrollTop - 24
    programmaticScrollRef.current = true
    if (programmaticTimerRef.current) clearTimeout(programmaticTimerRef.current)
    programmaticTimerRef.current = setTimeout(clearProgrammaticScroll, PROGRAMMATIC_SCROLL_WINDOW_MS)
    container.scrollTo({ top: offset, behavior: "smooth" })
  }, [clearProgrammaticScroll, container])
}
