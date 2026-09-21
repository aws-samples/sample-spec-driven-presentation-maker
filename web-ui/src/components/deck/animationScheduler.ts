// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

export const MAX_CONCURRENT = 2

type Release = () => void
type Waiter = { slug: string; resolve: (release: Release) => void }

let active = 0
const queue: Waiter[] = []

function makeRelease(): Release {
  let released = false
  return () => {
    if (released) return
    released = true
    active--
    drain()
  }
}

function drain() {
  while (active < MAX_CONCURRENT && queue.length > 0) {
    const next = queue.shift()!
    active++
    next.resolve(makeRelease())
  }
}

/** Acquire one of the two deck-wide animation slots in FIFO order. */
export function acquire(slug: string): Promise<Release> {
  return new Promise((resolve) => {
    queue.push({ slug, resolve })
    drain()
  })
}

interface TypewriterSpan {
  el: Element
  fullText: string
}

interface Typewriter {
  spans: TypewriterSpan[]
  charMs: number
  startedAt: number
  shown: number
}

const typewriters = new Set<Typewriter>()
let frameId: number | null = null

function applyCharacterCount(writer: Typewriter, count: number) {
  let remaining = count
  for (const span of writer.spans) {
    const nextLength = Math.min(span.fullText.length, Math.max(0, remaining))
    if (span.el.textContent?.length !== nextLength) {
      span.el.textContent = span.fullText.slice(0, nextLength)
    }
    remaining -= span.fullText.length
  }
}

export function advanceTypewriters(now: number) {
  for (const writer of typewriters) {
    const total = writer.spans.reduce((sum, span) => sum + span.fullText.length, 0)
    const shown = Math.min(total, Math.max(0, Math.floor((now - writer.startedAt) / writer.charMs)))
    if (shown !== writer.shown) {
      writer.shown = shown
      applyCharacterCount(writer, shown)
    }
    if (shown >= total) typewriters.delete(writer)
  }
}

function tick(now: number) {
  frameId = null
  advanceTypewriters(now)
  if (typewriters.size > 0) frameId = requestAnimationFrame(tick)
}

/** Register text spans with the single deck-wide typewriter frame loop. */
export function registerTypewriter(spans: TypewriterSpan[], charMs: number): () => void {
  const writer: Typewriter = {
    spans,
    charMs,
    startedAt: performance.now(),
    shown: 0,
  }
  typewriters.add(writer)
  if (frameId === null) frameId = requestAnimationFrame(tick)
  return () => typewriters.delete(writer)
}

/** Test-only reset for module singleton state. */
export function resetAnimationSchedulerForTests() {
  active = 0
  queue.splice(0)
  typewriters.clear()
  if (frameId !== null) cancelAnimationFrame(frameId)
  frameId = null
}
