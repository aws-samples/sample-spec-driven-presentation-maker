// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SSE Bridge — writes a chat's work-period events (lib/local/chat.ts) as server-sent events in
 * the strandsParser format the web-ui reads: `id: <n>` (the number the chat gave the event within
 * its period, for Last-Event-ID) and `data: <payload>`.
 *
 * A stream replays the buffered events first, then follows the live ones. An `end` event writes
 * its payload (an error), if any, and closes the stream; a replay that already holds the end
 * closes without subscribing, and a stream with nothing live to follow closes after its replay.
 * `onEnd` runs once the end was written, unless the reader went away before it (a closed tab).
 * A reader that goes away stops the subscription at once.
 *
 * Returns a ReadableStream that the API route can return as a Response.
 */
import type { BufferedEvent, SsePayload } from "./conversation/events"

interface BridgeOptions {
  subscribe?: (fn: (entry: BufferedEvent) => void) => () => void
  /** Buffered events to write before subscribing to live ones. */
  replay?: BufferedEvent[]
  /** The period's end was written to a reader that was still there. */
  onEnd?: () => void
}

export function createSSEStream({ subscribe, replay, onEnd }: BridgeOptions): ReadableStream {
  const encoder = new TextEncoder()
  let closed = false
  let cancelled = false
  let unsubscribe = () => {}

  return new ReadableStream({
    start(controller) {
      function send(id: number, payload: SsePayload) {
        try { controller.enqueue(encoder.encode(`id: ${id}\ndata: ${JSON.stringify(payload)}\n\n`)) } catch {}
      }

      /** Write one event; true when it ended the period and the stream closed. */
      function write({ id, event }: BufferedEvent): boolean {
        if (closed) return true
        if (event.payload) send(id, event.payload)
        if (event.kind !== "end") return false
        closed = true
        unsubscribe()
        try { controller.close() } catch {}
        if (!cancelled) onEnd?.()
        return true
      }

      for (const entry of replay ?? []) {
        if (write(entry)) return
      }
      if (subscribe) {
        unsubscribe = subscribe((entry) => { write(entry) })
      } else {
        closed = true
        try { controller.close() } catch {}
      }
    },
    cancel() {
      cancelled = true
      closed = true
      unsubscribe()
    },
  })
}
