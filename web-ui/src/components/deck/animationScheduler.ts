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
  shown: number
}

const typewriters = new Set<Typewriter>()
let frameId: number | null = null
let typewriterFrame = 0

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
    // Preserve the per-character feel after a long frame instead of dumping a word at once.
    const shown = Math.min(elapsedTarget, writer.shown + 4)
    if (shown !== writer.shown) {
      writer.shown = shown
      applyCharacterCount(writer, shown)
    }
    if (shown >= total) typewriters.delete(writer)
  }
}

function tick(now: number) {
  frameId = null
  typewriterFrame++
  // Limit DOM text mutations to 30 Hz while elapsed-time math preserves the
  // configured 15–50 ms character rate (the four-character cap catches up
  // by the same maximum amount as two characters on each 60 Hz frame).
  if (typewriterFrame % 2 === 0) advanceTypewriters(now)
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
  for (const waiter of queue.splice(0)) {
    waiter.signal?.removeEventListener("abort", waiter.abortWhileQueued!)
    waiter.resolve(null)
  }
  typewriters.clear()
  typewriterFrame = 0
  if (frameId !== null) cancelAnimationFrame(frameId)
  frameId = null
}
