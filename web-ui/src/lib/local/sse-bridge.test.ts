// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it, vi } from "vitest"

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
})
