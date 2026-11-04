// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect, vi } from "vitest"
import { parseEvent, parseStreamingChunk, resetParserState } from "./strandsParser.js"

describe("parseStreamingChunk error events", () => {
  const line = `data: ${JSON.stringify({ status: "error", code: "session_reload_required", error: "Reload the page" })}`

  it("appends the translated message when a translator is given", () => {
    const update = vi.fn()
    const translate = (code: string) => (code === "session_reload_required" ? "translated" : undefined)
    const out = parseStreamingChunk(line, "", update, undefined, translate)
    expect(out).toBe("\u26a0\ufe0f translated")
    expect(update).toHaveBeenCalledWith("\u26a0\ufe0f translated")
  })

  it("appends the English message without a translator", () => {
    const out = parseStreamingChunk(line, "", vi.fn())
    expect(out).toBe("\u26a0\ufe0f This page is out of date. Reload the page, then send again.")
  })
})

describe("parseEvent", () => {
  it("appends a text delta given as an object", () => {
    const update = vi.fn()
    const out = parseEvent({ event: { contentBlockDelta: { delta: { text: "hi" } } } }, "a", update)
    expect(out).toBe("ahi")
    expect(update).toHaveBeenCalledWith("ahi")
  })

  it("passes tool events to the tool callback", () => {
    resetParserState()
    const tool = vi.fn()
    parseEvent({ toolStart: { toolUseId: "t1", name: "read" } }, "", vi.fn(), tool)
    parseEvent({ toolResult: { toolUseId: "t1", name: "read", content: "{\"ok\":1}" } }, "", vi.fn(), tool)
    expect(tool.mock.calls[0][0]).toBe("read")
    expect(tool.mock.calls[1][1]).toMatchObject({ toolUseId: "t1", completed: true, result: { ok: 1 } })
  })

  it.each([
    [{ work: { state: "busy" } }],
    [{ turn: { id: "x", why: "prompt", text: "hi" } }],
    [{ turnEnd: { id: "x", how: "finished" } }],
    [{ steer: { id: "s", state: "accepted", text: "more" } }],
  ])("leaves the completion unchanged for a session event %j", (ev) => {
    const update = vi.fn()
    const tool = vi.fn()
    expect(parseEvent(ev, "text", update, tool)).toBe("text")
    expect(update).not.toHaveBeenCalled()
    expect(tool).not.toHaveBeenCalled()
  })

  it("gives the same result as the SSE line it came from", () => {
    const ev = { event: { contentBlockDelta: { delta: { text: "x" } } } }
    expect(parseStreamingChunk(`data: ${JSON.stringify(ev)}`, "", vi.fn())).toBe(parseEvent(ev, "", vi.fn()))
  })
})
