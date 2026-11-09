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

  it("appends the content-filter message for a filtered stop", () => {
    const filtered = `data: ${JSON.stringify({ status: "error", code: "content_filtered", error: "The model stopped its reply: content_filtered" })}`
    const out = parseStreamingChunk(filtered, "", vi.fn())
    expect(out).toBe("\u26a0\ufe0f The model stopped its reply because of its content filter. Rephrase your message and send it again.")
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

  it("passes a background dispatch as a running task", () => {
    const tool = vi.fn()
    parseEvent({ taskStart: { toolUseId: "c1", name: "compose_slides", taskId: "t-1" } }, "", vi.fn(), tool)
    expect(tool).toHaveBeenCalledWith("compose_slides", {
      toolUseId: "c1", name: "compose_slides", taskStarted: true, task: { id: "t-1", state: "running" },
    })
  })

  it.each([
    ["completed", "completed", JSON.stringify({ status: "success", slides: 4 }), "success", "completed"],
    ["failed", "failed", "boom", "error", "failed"],
    ["cancelled by the task manager", "cancelled", "", undefined, "cancelled"],
    ["a compose that stopped itself", "completed", JSON.stringify({ status: "cancelled" }), undefined, "cancelled"],
  ])("closes a background task: %s", (_name, status, content, cardStatus, state) => {
    const tool = vi.fn()
    parseEvent({ taskEnd: { toolUseId: "c1", name: "compose_slides", taskId: "t-1", status, content } }, "", vi.fn(), tool)
    const data = tool.mock.calls[0][1]
    expect(data).toMatchObject({ toolUseId: "c1", completed: true, rawResult: content, task: { id: "t-1", state } })
    expect(data.status).toBe(cardStatus)
  })

  it("leaves the completion unchanged for a composer note", () => {
    const tool = vi.fn()
    expect(parseEvent({ composerNote: { toolUseId: "c1", group: 1, slugs: "a", text: "done" } }, "t", vi.fn(), tool)).toBe("t")
    expect(tool).not.toHaveBeenCalled()
  })
})
