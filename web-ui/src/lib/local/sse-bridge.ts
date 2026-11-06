// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SSE Bridge — writes a turn's chat events (lib/local/conversation) as server-sent events in
 * the strandsParser format the web-ui reads: `id: <n>` (the number the process manager gave the
 * event, for Last-Event-ID) and `data: <payload>`.
 *
 * A stream replays the buffered events first, then follows the live ones. An `end` event writes
 * its payload (an error), if any, and closes the stream; a replay that already holds the end
 * closes without subscribing.
 *
 * Returns a ReadableStream that the API route can return as a Response.
 */
import type { BufferedEvent, SsePayload } from "./conversation/events"

interface BridgeOptions {
  subscribe: (fn: (entry: BufferedEvent) => void) => () => void
  /** Buffered events to write before subscribing to live ones. */
  replay?: BufferedEvent[]
}

export function createSSEStream({ subscribe, replay }: BridgeOptions): ReadableStream {
  const encoder = new TextEncoder()

  return new ReadableStream({
    start(controller) {
      let closed = false
      let unsubscribe = () => {}

      function send(id: number, payload: SsePayload) {
        try { controller.enqueue(encoder.encode(`id: ${id}\ndata: ${JSON.stringify(payload)}\n\n`)) } catch {}
      }

      /** Write one event; true when it ended the turn and the stream closed. */
      function write({ id, event }: BufferedEvent): boolean {
        if (closed) return true
        if (event.payload) send(id, event.payload)
        if (event.kind !== "end") return false
        closed = true
        unsubscribe()
        try { controller.close() } catch {}
        return true
      }

      for (const entry of replay ?? []) {
        if (write(entry)) return
      }
      unsubscribe = subscribe((entry) => { write(entry) })
    },
  })
}
