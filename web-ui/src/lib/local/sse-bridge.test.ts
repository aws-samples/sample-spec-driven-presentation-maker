// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import path from "path"
import { describe, expect, it, vi } from "vitest"

import { DECK_ROOT } from "./deck-paths"
import { createSSEStream } from "./sse-bridge"

describe("createSSEStream", () => {
  it("forwards JSON-RPC errors and closes the stream", async () => {
    let listener: ((message: Record<string, unknown>) => void) | undefined
    const unsubscribe = vi.fn()
    const onError = vi.fn()
    const stream = createSSEStream({
      sessionId: "11111111-1111-4111-8111-111111111111",
      subscribe: (next) => {
        listener = next
        return unsubscribe
      },
      onError,
    })
    const reader = stream.getReader()

    listener?.({ id: 1, error: { message: "prompt failed" } })

    const first = await reader.read()
    expect(new TextDecoder().decode(first.value)).toContain(
      'data: {"status":"error","error":"prompt failed"}',
    )
    await expect(reader.read()).resolves.toMatchObject({ done: true })
    expect(onError).toHaveBeenCalledOnce()
    expect(unsubscribe).toHaveBeenCalledOnce()
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
