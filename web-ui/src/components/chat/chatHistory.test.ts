// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect } from "vitest"
import { isLocalHistoryFormat, parseLocalHistory, parseCloudHistory } from "./chatHistory"
import type { ChatMessage } from "@/services/deckService"

const asHistory = (msgs: unknown[]) => msgs as unknown as ChatMessage[]

describe("isLocalHistoryFormat", () => {
  it("detects local format by toolUses on the first message", () => {
    expect(isLocalHistoryFormat(asHistory([{ role: "user", content: "hi", toolUses: [] }]))).toBe(true)
    expect(isLocalHistoryFormat(asHistory([{ role: "user", content: "hi" }]))).toBe(false)
  })
})

describe("parseLocalHistory", () => {
  it("normalizes messages and defaults missing fields", () => {
    const out = parseLocalHistory(asHistory([
      { role: "user", content: "hello", toolUses: [] },
      { content: 42, toolUses: undefined },
    ]))
    expect(out[0]).toMatchObject({ role: "user", content: "hello", toolUses: [] })
    expect(out[1]).toMatchObject({ role: "assistant", content: "", toolUses: [] })
  })
})

describe("parseCloudHistory", () => {
  it("parses plain string messages and strips sdpm markers", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: "<!--sdpm:mode=spec-->\nmake slides" },
    ]))
    expect(out).toHaveLength(1)
    expect(out[0].content).toBe("make slides")
  })

  it("skips empty messages", () => {
    const out = parseCloudHistory(asHistory([{ role: "assistant", content: "   " }]))
    expect(out).toHaveLength(0)
  })

  it("extracts toolUse blocks and builds blocks for assistant messages", () => {
    const out = parseCloudHistory(asHistory([
      {
        role: "assistant",
        content: [
          { text: "Creating deck" },
          { toolUse: { toolUseId: "t1", name: "create_deck", input: { title: "X" } } },
        ],
      },
    ]))
    expect(out[0].toolUses).toEqual([{ toolUseId: "t1", name: "create_deck", input: { title: "X" } }])
    expect(out[0].blocks).toHaveLength(2)
  })

  it("folds toolResult user messages into the preceding assistant toolUse", () => {
    const out = parseCloudHistory(asHistory([
      {
        role: "assistant",
        content: [
          { text: "Working" },
          { toolUse: { toolUseId: "t1", name: "generate_pptx", input: {} } },
        ],
      },
      {
        role: "user",
        content: [
          { toolResult: { toolUseId: "t1", status: "success", content: [{ text: '{"ok":true}' }] } },
        ],
      },
    ]))
    // toolResult message is folded, not emitted
    expect(out).toHaveLength(1)
    expect(out[0].toolUses[0].status).toBe("success")
    expect(out[0].toolUses[0].result).toEqual({ ok: true })
    const toolBlock = out[0].blocks?.find((b) => b.type === "tool")
    expect(toolBlock && toolBlock.type === "tool" ? toolBlock.tool.status : undefined).toBe("success")
  })

  it("keeps non-JSON tool results as raw text", () => {
    const out = parseCloudHistory(asHistory([
      { role: "assistant", content: [{ toolUse: { toolUseId: "t1", name: "x", input: {} } }] },
      { role: "user", content: [{ toolResult: { toolUseId: "t1", status: "error", content: [{ text: "boom" }] } }] },
    ]))
    expect(out[0].toolUses[0].status).toBe("error")
    expect(out[0].toolUses[0].result).toBe("boom")
  })

  it("derives attachments from Attached markers in user text", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: '[Attached:{"v":1,"name":"report.pdf","source":"uploads/user/123e4567-e89b-12d3-a456-426614174000/report.pdf"}] summarize this' },
    ]))
    expect(out[0].attachments).toEqual([{ fileName: "report.pdf", fileType: "application/pdf" }])
  })
})
