// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

export const MAX_CONCURRENT = 2

export type Release = () => void
type Waiter = {
  slug: string
  signal?: AbortSignal
  resolve: (release: Release | null) => void
  abortWhileQueued?: () => void
}

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

function grant(waiter: Waiter) {
  waiter.signal?.removeEventListener("abort", waiter.abortWhileQueued!)
  if (waiter.signal?.aborted) {
    waiter.resolve(null)
    return
  }

  active++
  const releaseSlot = makeRelease()
  const abortAfterGrant = () => releaseSlot()
  waiter.signal?.addEventListener("abort", abortAfterGrant, { once: true })
  waiter.resolve(() => {
    waiter.signal?.removeEventListener("abort", abortAfterGrant)
    releaseSlot()
  })
}

function drain() {
  while (active < MAX_CONCURRENT && queue.length > 0) {
    grant(queue.shift()!)
  }
}

/** Acquire one of the two deck-wide animation slots in FIFO order. */
export function acquire(slug: string, signal?: AbortSignal): Promise<Release | null> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve(null)
      return
    }
    const waiter: Waiter = { slug, signal, resolve }
    waiter.abortWhileQueued = () => {
      const index = queue.indexOf(waiter)
      if (index >= 0) queue.splice(index, 1)
      resolve(null)
    }
    signal?.addEventListener("abort", waiter.abortWhileQueued, { once: true })
    queue.push(waiter)
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
  lastFrameAt: number
  shown: number
}

const typewriters = new Set<Typewriter>()
/** Test-only access to the live registry. */
export const typewritersForTests = typewriters
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
    const elapsedTarget = Math.min(total, Math.max(0, Math.floor((now - writer.startedAt) / writer.charMs)))
    // Follow the elapsed-time target exactly (this is what the original
    // setInterval(charMs) did), so cadence matches within one character.
    // Only after a stalled frame (> 4 chars behind) do we cap catch-up at 2,
    // so a long frame cannot dump a whole word at once.
    const behind = elapsedTarget - writer.shown
    const shown = behind > 4 ? writer.shown + 2 : elapsedTarget
    writer.lastFrameAt = now
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
  const startedAt = performance.now()
  const writer: Typewriter = {
    spans,
    charMs,
    startedAt,
    lastFrameAt: startedAt,
    shown: 0,
  }
  typewriters.add(writer)
  if (frameId === null) frameId = requestAnimationFrame(tick)
  return () => typewriters.delete(writer)
}

/** Test-only reset for module singleton state. */
export function resetAnimationSchedulerForTests() {
  active = 0
  for (const waiter of queue.splice(0)) {
    waiter.signal?.removeEventListener("abort", waiter.abortWhileQueued!)
    waiter.resolve(null)
  }
  typewriters.clear()
  if (frameId !== null) cancelAnimationFrame(frameId)
  frameId = null
}
