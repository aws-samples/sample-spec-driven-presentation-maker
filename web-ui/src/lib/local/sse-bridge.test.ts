// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import path from "path"
import { describe, expect, it, vi } from "vitest"

import { DECK_ROOT } from "./deck-paths"
import { createSSEStream } from "./sse-bridge"
import { STEER_EVENT } from "./steer"
import { TURN_END, TURN_ERROR } from "./turnErrors"

const SID = "11111111-1111-4111-8111-111111111111"

/** A bridge on a fake subscription; `push` delivers a live message, `events` reads the stream to its end. */
function bridge(opts: { replay?: { id: number; msg: Record<string, unknown> }[] } = {}) {
  let listener: ((message: Record<string, unknown>) => void) | undefined
  const unsubscribe = vi.fn()
  const subscribe = vi.fn((next: (message: Record<string, unknown>) => void) => { listener = next; return unsubscribe })
  const onError = vi.fn()
  const onDone = vi.fn()
  const stream = createSSEStream({ sessionId: SID, subscribe, onError, onDone, replay: opts.replay })
  const events = async () => {
    const text = await new Response(stream).text()
    return text.split("\n\n").filter(Boolean).map((b) => JSON.parse(b.split("\n").find((l) => l.startsWith("data: "))!.slice(6)))
  }
  return { push: (m: Record<string, unknown>) => listener?.(m), events, subscribe, unsubscribe, onError, onDone }
}

const text = (t: string) => ({ method: "session/update", params: { sessionId: SID, update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: t } } } })
const turnEnd = (stopReason: string) => ({ method: TURN_END, params: { sessionId: SID, stopReason } })

describe("createSSEStream", () => {
  it("forwards a failed prompt and closes the stream", async () => {
    const b = bridge()
    b.push({ method: TURN_ERROR, params: { sessionId: SID, message: "Internal error: prompt failed" } })
    expect(await b.events()).toEqual([{ status: "error", error: "Internal error: prompt failed" }])
    expect(b.onError).toHaveBeenCalledOnce()
    expect(b.unsubscribe).toHaveBeenCalledOnce()
  })

  it("closes with agent_exited when kiro-cli exits mid-turn", async () => {
    const b = bridge()
    b.push(text("partial"))
    b.push({ method: TURN_ERROR, params: { sessionId: SID, code: "agent_exited", message: "kiro-cli exited with code null" } })
    const events = await b.events()
    expect(events.at(-1)).toMatchObject({ status: "error", code: "agent_exited", error: expect.stringMatching(/kiro-cli stopped/) })
    expect(b.onError).toHaveBeenCalledOnce()
  })

  it.each(["end_turn", "cancelled", "some_future_reason"])("closes quietly on stopReason %s", async (stopReason) => {
    const b = bridge()
    b.push(text("hi"))
    b.push(turnEnd(stopReason))
    expect(await b.events()).toEqual([{ event: { contentBlockDelta: { delta: { text: "hi" } } } }])
    expect(b.onError).not.toHaveBeenCalled()
    expect(b.onDone).toHaveBeenCalledOnce()
  })

  it.each(["refusal", "max_tokens", "max_turn_requests"])("closes on stopReason %s with its code after the text", async (stopReason) => {
    const b = bridge()
    b.push(text("hi"))
    b.push(turnEnd(stopReason))
    const events = await b.events()
    expect(events).toHaveLength(2)
    expect(events[1]).toMatchObject({ status: "error", code: stopReason })
    expect(b.onDone).toHaveBeenCalledOnce()
  })

  it("forwards a steer's states in the Cloud steer event's shape, between the turn's text", async () => {
    const b = bridge()
    b.push(text("one "))
    b.push({ method: STEER_EVENT, params: { sessionId: SID, id: "m1", text: "stop", state: "accepted" } })
    b.push({ method: STEER_EVENT, params: { sessionId: SID, id: "m1", state: "delivered" } })
    b.push(text("STOPPED"))
    b.push({ method: STEER_EVENT, params: { sessionId: SID, id: "m2", state: "discarded" } })
    b.push(turnEnd("cancelled"))
    expect(await b.events()).toEqual([
      { event: { contentBlockDelta: { delta: { text: "one " } } } },
      { steer: { id: "m1", text: "stop", state: "accepted" } },
      { steer: { id: "m1", state: "delivered" } },
      { event: { contentBlockDelta: { delta: { text: "STOPPED" } } } },
      { steer: { id: "m2", state: "discarded" } },
    ])
  })

  it("ignores JSON-RPC answers to other requests", async () => {
    const b = bridge()
    b.push({ id: 7, error: { message: "set_config_option failed" } })
    b.push({ id: 8, result: { stopReason: "end_turn" } })
    b.push(text("still here"))
    b.push(turnEnd("end_turn"))
    expect(await b.events()).toEqual([{ event: { contentBlockDelta: { delta: { text: "still here" } } } }])
  })

  it("closes a reconnect whose replay already holds the end of the turn, without subscribing", async () => {
    const b = bridge({ replay: [{ id: 1, msg: text("done") }, { id: 2, msg: turnEnd("end_turn") }] })
    expect(await b.events()).toEqual([{ event: { contentBlockDelta: { delta: { text: "done" } } } }])
    expect(b.subscribe).not.toHaveBeenCalled()
  })

  it("takes the deck id from a deck's output_dir but not from the deck root", () => {
    const sessionId = "22222222-2222-4222-8222-222222222222"
    let listener: ((message: Record<string, unknown>) => void) | undefined
    const onDeckId = vi.fn()
    createSSEStream({ sessionId, subscribe: (next) => { listener = next; return () => {} }, onDeckId })
    const completed = (toolCallId: string, result: Record<string, unknown>) => listener?.({
      method: "session/update",
      params: {
        sessionId,
        update: {
          sessionUpdate: "tool_call_update", toolCallId, status: "completed",
          rawOutput: { items: [{ Json: { content: [{ text: JSON.stringify(result) }] } }] },
        },
      },
    })

    completed("t1", { output_dir: DECK_ROOT })
    completed("t2", { output_dir: path.join(DECK_ROOT, "20261101-1648-review") })

    expect(onDeckId.mock.calls).toEqual([["20261101-1648-review"]])
  })
})
