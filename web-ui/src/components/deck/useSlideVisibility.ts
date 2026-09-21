// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useEffect, useRef, type RefObject } from "react"

export type SlideVisibility = "unknown" | "visible" | "hidden"
type VisibilityListener = (visibility: Exclude<SlideVisibility, "unknown">) => void
interface ObserverEntry {
  observer: IntersectionObserver
  listeners: Map<Element, Set<VisibilityListener>>
}

const observers = new Map<Element | null, Map<number, ObserverEntry>>()

function observerFor(root: Element | null, threshold: number): ObserverEntry {
  let byThreshold = observers.get(root)
  if (!byThreshold) {
    byThreshold = new Map()
    observers.set(root, byThreshold)
  }
  let entry = byThreshold.get(threshold)
  if (!entry) {
    const listeners = new Map<Element, Set<VisibilityListener>>()
    const observer = new IntersectionObserver((changes) => {
      for (const change of changes) {
        const visibility = change.isIntersecting && change.intersectionRatio >= threshold
          ? "visible"
          : "hidden"
        listeners.get(change.target)?.forEach((listener) => listener(visibility))
      }
    }, { root, threshold: [0, threshold] })
    entry = { observer, listeners }
    byThreshold.set(threshold, entry)
  }
  return entry
}

/** Track slide visibility without causing React renders. */
export function useSlideVisibility<T extends Element>(
  ref: RefObject<T | null>,
  threshold = 0.5,
  onChange?: (visibility: Exclude<SlideVisibility, "unknown">) => void,
) {
  const visibilityRef = useRef<SlideVisibility>("unknown")
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEffect(() => {
    const element = ref.current
    if (!element) return
    if (typeof IntersectionObserver === "undefined") {
      visibilityRef.current = "visible"
      onChangeRef.current?.("visible")
      return
    }
    const root = element.closest("[data-slide-scroller]")
    const entry = observerFor(root, threshold)
    const listener: VisibilityListener = (visibility) => {
      visibilityRef.current = visibility
      onChangeRef.current?.(visibility)
    }
    const listeners = entry.listeners.get(element) ?? new Set<VisibilityListener>()
    listeners.add(listener)
    entry.listeners.set(element, listeners)
    entry.observer.observe(element)

    return () => {
      listeners.delete(listener)
      if (listeners.size === 0) {
        entry.listeners.delete(element)
        entry.observer.unobserve(element)
      }
      if (entry.listeners.size === 0) {
        entry.observer.disconnect()
        const byThreshold = observers.get(root)
        byThreshold?.delete(threshold)
        if (byThreshold?.size === 0) observers.delete(root)
      }
    }
  }, [ref, threshold])

  return visibilityRef
}
