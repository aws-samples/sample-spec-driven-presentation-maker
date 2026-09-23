// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: true }))

import { forkKiroSession } from "./kiroSessionsService"

const origin = {
  sourceSessionId: "11111111-1111-4111-8111-111111111111",
  title: "Investigate rendering latency",
  cwd: "/work/alpha",
  updatedAt: "2026-09-22T10:00:00.000Z",
  forkedAt: "2026-09-23T00:00:00.000Z",
}

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  }), { status: 200, headers: { "Content-Type": "text/event-stream" } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("forkKiroSession", () => {
  it("parses phase and done events across arbitrary stream chunks", async () => {
    const sessionId = "22222222-2222-4222-8222-222222222222"
    const payload = [
      'event: phase\ndata: {"phase":"copying"}\n\n',
      'event: phase\ndata: {"phase":"starting"}\n\n',
      'event: phase\ndata: {"phase":"loading","replayed":20}\n\n',
      'event: phase\ndata: {"phase":"switching"}\n\n',
      `event: done\ndata: ${JSON.stringify({ sessionId, origin })}\n\n`,
    ].join("")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse([
      payload.slice(0, 17),
      payload.slice(17, 83),
      payload.slice(83, 151),
      payload.slice(151),
    ])))
    const onPhase = vi.fn()
    const controller = new AbortController()

    await expect(forkKiroSession({
      sourceSessionId: origin.sourceSessionId,
      clientSessionId: "client-session",
    }, { onPhase, signal: controller.signal })).resolves.toEqual({ sessionId, origin })

    expect(onPhase.mock.calls).toEqual([
      ["copying", undefined],
      ["starting", undefined],
      ["loading", { replayed: 20 }],
      ["switching", undefined],
    ])
    expect(fetch).toHaveBeenCalledWith("/api/agent/sessions/fork", expect.objectContaining({
      method: "POST",
      signal: controller.signal,
    }))
  })

  it("rejects with the server error code from an SSE error event", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse([
      'event: error\ndata: {"error":"source not found","code":404}\n\n',
    ])))

    await expect(forkKiroSession({
      sourceSessionId: origin.sourceSessionId,
      clientSessionId: "client-session",
    })).rejects.toThrow("Failed to fork kiro session (404): source not found")
  })
})
