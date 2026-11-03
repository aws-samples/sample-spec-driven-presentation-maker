// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect, vi } from "vitest"
import { parseStreamingChunk } from "./strandsParser.js"

describe("parseStreamingChunk error events", () => {
  const line = `data: ${JSON.stringify({ status: "error", code: "session_reload_required", error: "Reload the page" })}`

  it("appends the translated message when a translator is given", () => {
    const update = vi.fn()
    const translate = (code: string) => (code === "session_reload_required" ? "translated" : undefined)
    const out = parseStreamingChunk(line, "", update, undefined, translate)
    expect(out).toBe("⚠️ translated")
    expect(update).toHaveBeenCalledWith("⚠️ translated")
  })

  it("appends the English message without a translator", () => {
    const out = parseStreamingChunk(line, "", vi.fn())
    expect(out).toBe("⚠️ This page is out of date. Reload the page, then send again.")
  })
})
