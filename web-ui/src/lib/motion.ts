// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Layout motion — moves real elements (height, width, margins) with the Web Animations API,
 * so text keeps reflowing while it moves. Nothing animates where the API is missing (tests)
 * or the user asked for reduced motion.
 */

/** Long enough to follow, short enough not to wait for. */
export const MORPH_MS = 720
/** Ease in and out: a move that starts and lands gently (an ease-out alone jumps most of the way at once). */
export const MORPH_EASE = "cubic-bezier(0.65, 0, 0.35, 1)"

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

/** The element can be animated (the API exists and motion is allowed). */
export function canAnimate(el: Element | null | undefined): el is HTMLElement {
  return !!el && typeof (el as HTMLElement).animate === "function" && !prefersReducedMotion()
}

/** Desktop layout (the chat sheet sits beside the page). */
export function isDesktop(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(min-width: 640px)").matches
}

/** Grow an element from no height to its own height, fading it in. */
export function revealHeight(el: HTMLElement, duration = MORPH_MS): Animation | null {
  if (!canAnimate(el)) return null
  const h = el.offsetHeight
  const overflow = el.style.overflow
  el.style.overflow = "hidden"
  const a = el.animate(
    [{ height: "0px", opacity: 0 }, { height: `${h}px`, opacity: 1 }],
    { duration, easing: MORPH_EASE },
  )
  a.finished.finally(() => { el.style.overflow = overflow }).catch(() => {})
  return a
}

/** Shrink an element to no height, fading it out; it stays at no height until removed. */
export function collapseHeight(el: HTMLElement, duration = MORPH_MS): Animation | null {
  if (!canAnimate(el)) return null
  el.style.overflow = "hidden"
  return el.animate(
    [{ height: `${el.offsetHeight}px`, opacity: 1 }, { height: "0px", opacity: 0 }],
    { duration, easing: MORPH_EASE, fill: "forwards" },
  )
}
