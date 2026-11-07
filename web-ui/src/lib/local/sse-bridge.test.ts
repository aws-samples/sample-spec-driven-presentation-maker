// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The SSE bridge writes the process manager's numbered chat events as they are: `id:` is the
 * event's number, for live and replayed events alike; an end event writes its payload, if any,
 * and closes the stream; a replay that holds the end closes it without subscribing.
 */

import { describe, expect, it, vi } from "vitest"

import type { BufferedEvent, ChatEvent, SsePayload } from "./conversation/events"
import { createSSEStream } from "./sse-bridge"

const text = (t: string): SsePayload => ({ event: { contentBlockDelta: { delta: { text: t } } } })
const data = (id: number, payload: SsePayload): BufferedEvent => ({ id, event: { kind: "data", payload } })
const end = (id: number, extra: Omit<Extract<ChatEvent, { kind: "end" }>, "kind"> = {}): BufferedEvent => ({ id, event: { kind: "end", ...extra } })

/** A bridge on a fake subscription; `push` delivers a live event, `blocks` reads the stream to its end. */
function bridge(replay?: BufferedEvent[]) {
  let listener: ((entry: BufferedEvent) => void) | undefined
  const unsubscribe = vi.fn()
  const subscribe = vi.fn((next: (entry: BufferedEvent) => void) => { listener = next; return unsubscribe })
  const stream = createSSEStream({ subscribe, replay })
  const blocks = async () => {
    const body = await new Response(stream).text()
    return body.split("\n\n").filter(Boolean).map((block) => {
      const lines = block.split("\n")
      return {
        id: Number(lines.find((l) => l.startsWith("id: "))!.slice(4)),
        data: JSON.parse(lines.find((l) => l.startsWith("data: "))!.slice(6)),
      }
    })
  }
  return { push: (entry: BufferedEvent) => listener?.(entry), blocks, subscribe, unsubscribe }
}

describe("createSSEStream", () => {
  it("writes each event under its own number and closes quietly on an end without payload", async () => {
    const b = bridge()
    b.push(data(4, text("hi")))
    b.push(data(5, { steer: { id: "m1", state: "delivered" } }))
    b.push(end(6, { stopReason: "end_turn" }))
    expect(await b.blocks()).toEqual([
      { id: 4, data: text("hi") },
      { id: 5, data: { steer: { id: "m1", state: "delivered" } } },
    ])
    expect(b.unsubscribe).toHaveBeenCalledOnce()
  })

  it("writes an end's error payload last, then closes", async () => {
    const b = bridge()
    b.push(data(1, text("partial")))
    b.push(end(2, { payload: { status: "error", code: "agent_exited", error: "kiro-cli stopped" } }))
    b.push(data(3, text("after the end")))
    expect(await b.blocks()).toEqual([
      { id: 1, data: text("partial") },
      { id: 2, data: { status: "error", code: "agent_exited", error: "kiro-cli stopped" } },
    ])
  })

  it("replays the buffered events with their numbers before the live ones", async () => {
    const b = bridge([data(1, { notice: { code: "context_not_carried_over" } }), data(2, text("one "))])
    expect(b.subscribe).toHaveBeenCalledOnce()
    b.push(data(3, text("two")))
    b.push(end(4))
    expect((await b.blocks()).map((block) => block.id)).toEqual([1, 2, 3])
  })

  it("closes a reconnect whose replay already holds the end of the turn, without subscribing", async () => {
    const b = bridge([data(1, text("done")), end(2, { stopReason: "end_turn" })])
    expect(await b.blocks()).toEqual([{ id: 1, data: text("done") }])
    expect(b.subscribe).not.toHaveBeenCalled()
  })
})
