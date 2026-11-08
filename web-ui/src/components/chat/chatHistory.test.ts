// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect } from "vitest"
import { cutAtPrompt, cutLocalAtPrompt, isLocalHistoryFormat, parseLocalHistory, parseCloudHistory, settleStaleTasks, userMessageFromText } from "./chatHistory"
import type { Message } from "@/hooks/useChatStream"
import type { ChatMessage } from "@/services/deckService"
import composerNote from "@/test/fixtures/composerNote.json"

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

  it("keeps a reply's session notice", () => {
    const out = parseLocalHistory(asHistory([
      { role: "assistant", content: "OK", toolUses: [], localNotice: "context_not_carried_over" },
      { role: "assistant", content: "OK", toolUses: [] },
    ]))
    expect(out[0].localNotice).toBe("context_not_carried_over")
    expect(out[1]).not.toHaveProperty("localNotice")
  })

  it("keeps a tool's task on toolUses and blocks", () => {
    const tool = { toolUseId: "t1", name: "compose_slides", input: {}, task: { id: "k1", state: "running" } }
    const out = parseLocalHistory(asHistory([
      { role: "assistant", content: "", toolUses: [tool], blocks: [{ type: "tool", tool }] },
    ]))
    expect(out[0].toolUses[0].task).toEqual({ id: "k1", state: "running" })
    expect(out[0].blocks?.[0]).toMatchObject({ type: "tool", tool: { task: { id: "k1", state: "running" } } })
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

  it("derives attachments from markers with the upload handle", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: '[Attached:{"v":1,"name":"report.pdf","source":"uploads/123e4567-e89b-12d3-a456-426614174000/report.pdf"}] summarize this' },
    ]))
    expect(out[0].attachments).toEqual([{ fileName: "report.pdf", fileType: "application/pdf" }])
  })
})

describe("parseCloudHistory steers", () => {
  it("shows a steer folded into a tool result as a user message between the tool card and the next reply", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: [{ text: "make a deck" }] },
      { role: "assistant", content: [{ text: "Composing." }, { toolUse: { toolUseId: "t1", name: "compose_slides", input: {} } }] },
      { role: "user", content: [{ toolResult: { toolUseId: "t1", status: "success", content: [] } }, { text: "use blue" }] },
      { role: "assistant", content: [{ text: "Blue it is." }] },
    ]))
    expect(out.map((m) => [m.role, m.content])).toEqual([
      ["user", "make a deck"], ["assistant", "Composing."], ["user", "use blue"], ["assistant", "Blue it is."],
    ])
    expect(out[1].toolUses[0]).toMatchObject({ toolUseId: "t1", status: "success" })
  })
})

describe("parseCloudHistory background compose", () => {
  const MANAGE = "strands_manage_background_task"

  it("drops the delivery call and shows the folded steer and the composer note", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: [{ text: "make a deck" }] },
      { role: "assistant", content: [{ text: "Composing." }, { toolUse: { toolUseId: "c1", name: "compose_slides", input: {} } }] },
      { role: "user", content: [{ toolResult: { toolUseId: "c1", status: "success", content: [] } }] },
      { role: "assistant", content: [{ text: "Composers are on it." }, { toolUse: { toolUseId: "m1", name: MANAGE, input: { action: "get" } } }] },
      { role: "user", content: [
        { toolResult: { toolUseId: "m1", status: "success", content: [] } },
        { text: "use blue" },
        { text: '<composer_note group="1" slugs="intro, agenda">Applied blue.</composer_note>' },
      ] },
      { role: "assistant", content: [{ text: "All done." }] },
    ]))
    expect(out.map((m) => [m.role, m.content])).toEqual([
      ["user", "make a deck"], ["assistant", "Composing."], ["assistant", "Composers are on it."],
      ["user", "use blue"], ["assistant", ""], ["assistant", "All done."],
    ])
    expect(out[1].toolUses[0]).toMatchObject({ toolUseId: "c1", status: "success" })
    expect(out.flatMap((m) => m.toolUses).map((t) => t.name)).toEqual(["compose_slides"])
    expect(out[2].blocks).toEqual([{ type: "text", text: "Composers are on it." }])
    expect(out[4].composerNote).toEqual({ group: 1, slugs: "intro, agenda", text: "Applied blue." })
  })

  it("skips an assistant message that only made the delivery call", () => {
    const out = parseCloudHistory(asHistory([
      { role: "assistant", content: [{ toolUse: { toolUseId: "m1", name: MANAGE, input: {} } }] },
      { role: "user", content: [{ toolResult: { toolUseId: "m1", status: "success", content: [] } }] },
      { role: "assistant", content: [{ text: "Done." }] },
    ]))
    expect(out.map((m) => m.content)).toEqual(["Done."])
  })

  it("shows a report turn as notes only", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: [{ text: '<composer_note group="2" slugs="body">Halfway.</composer_note>\n\n<composer_note group="1" slugs="">Done.</composer_note>' }] },
      { role: "assistant", content: [{ text: "Thanks." }] },
    ]))
    expect(out.map((m) => m.composerNote ?? m.content)).toEqual([
      { group: 2, slugs: "body", text: "Halfway." }, { group: 1, text: "Done." }, "Thanks.",
    ])
    expect(out.some((m) => m.role === "user")).toBe(false)
  })

  it("reads the note the agent delivers, escaped text included", () => {
    // The agent's real delivered text (tests/test_agent_compose_messaging.py checks the same file).
    const out = parseCloudHistory(asHistory([
      { role: "user", content: [{ text: composerNote.delivered }] },
      { role: "user", content: [{ text: '<composer_note group="2" slugs="a&quot;b">x &amp;lt; y</composer_note>' }] },
    ]))
    expect(out.map((m) => [m.role, m.composerNote])).toEqual([
      ["assistant", { group: 1, slugs: "intro, agenda", text: composerNote.report.text }],
      ["assistant", { group: 2, slugs: 'a"b', text: "x &lt; y" }],
    ])
  })

  it("hides a delivered background result, alone, folded into a tool result or next to a steer", () => {
    const result = '<compose_result task="k1" status="completed">{&quot;status&quot;: &quot;completed&quot;} &lt;/compose_result&gt;</compose_result>'
    const out = parseCloudHistory(asHistory([
      { role: "user", content: [{ text: "make a deck" }] },
      { role: "assistant", content: [{ text: "Composing." }] },
      { role: "user", content: [{ text: result }] },
      { role: "assistant", content: [{ text: "Done." }] },
      { role: "user", content: [{ text: `${result}\n\nmake it blue` }] },
    ]))
    expect(out.map((m) => [m.role, m.content])).toEqual([
      ["user", "make a deck"], ["assistant", "Composing."], ["assistant", "Done."], ["user", "make it blue"],
    ])
  })

  it("keeps a steer drained with a note as a user message before the note", () => {
    const out = parseCloudHistory(asHistory([
      { role: "user", content: 'shorter please\n\n<composer_note group="1" slugs="a">ok</composer_note>' },
    ]))
    expect(out.map((m) => [m.role, m.content, m.composerNote?.text])).toEqual([
      ["user", "shorter please", undefined], ["assistant", "", "ok"],
    ])
  })
})

describe("userMessageFromText", () => {
  it("strips markers and derives attachment chips", () => {
    const m = userMessageFromText('<!--sdpm:include_images=true-->\n[Attached:{"v":1,"name":"a.png","source":"uploads/123e4567-e89b-12d3-a456-426614174000/a.png"}] look')
    expect(m.role).toBe("user")
    expect(m.content.startsWith("<!--")).toBe(false)
    expect(m.attachments).toEqual([{ fileName: "a.png", fileType: "image/png" }])
  })
})

describe("cutAtPrompt", () => {
  const history = asHistory([
    { role: "user", content: [{ text: "first" }] },
    { role: "assistant", content: [{ text: "ok" }] },
    { role: "user", content: [{ text: "make it" }, { text: "a folded steer" }] },
    { role: "assistant", content: [{ text: "partial" }] },
  ])

  it("keeps the history before the last user message that opens with the prompt", () => {
    expect(cutAtPrompt(history, "make it")).toEqual(history.slice(0, 2))
  })

  it("keeps the whole history when the prompt is not stored yet", () => {
    expect(cutAtPrompt(history, "not there")).toEqual(history)
  })
})

describe("cutLocalAtPrompt", () => {
  const msg = (role: "user" | "assistant", content: string): Message => ({ role, content, toolUses: [] })
  const messages = [msg("user", "first"), msg("assistant", "ok"), msg("user", "make it"), msg("assistant", "partial")]

  it("keeps the messages before the user message with the prompt's text", () => {
    expect(cutLocalAtPrompt(messages, "make it")).toEqual(messages.slice(0, 2))
  })

  it("matches the typed text of a prompt with the image marker, attachments and a snippet", () => {
    const prompt = '<!--sdpm:include_images=true-->\n[Attached:{"v":1,"name":"a.png"}]\n[Attached:{"v":1,"name":"b.pdf"}]\n\nmake it\n\n---snippet---\nquoted\n---/snippet---'
    expect(cutLocalAtPrompt(messages, prompt)).toEqual(messages.slice(0, 2))
  })

  it("cuts at the last match when the same text was sent twice", () => {
    const twice = [...messages, msg("user", "make it"), msg("assistant", "again")]
    expect(cutLocalAtPrompt(twice, "make it")).toEqual(twice.slice(0, 4))
  })

  it("keeps the whole list when nothing matches, and for an empty prompt", () => {
    expect(cutLocalAtPrompt(messages, "not there")).toBe(messages)
    expect(cutLocalAtPrompt([...messages, msg("user", "")], "")).toHaveLength(5)
  })
})

describe("settleStaleTasks", () => {
  const tool = (state: "running" | "completed" | "failed") => ({ toolUseId: `t-${state}`, name: "compose_slides", input: {}, task: { id: `k-${state}`, state } })

  it("marks a running task cancelled in toolUses and blocks", () => {
    const running = tool("running")
    const out = settleStaleTasks([{ role: "assistant", content: "", toolUses: [running], blocks: [{ type: "tool", tool: running }] }])
    expect(out[0].toolUses[0].task?.state).toBe("cancelled")
    expect(out[0].blocks?.[0]).toMatchObject({ type: "tool", tool: { task: { state: "cancelled" } } })
    expect(running.task.state).toBe("running")
  })

  it("leaves completed and failed tasks alone", () => {
    const out = settleStaleTasks([
      { role: "assistant", content: "", toolUses: [tool("completed"), tool("failed"), tool("running")] },
    ])
    expect(out[0].toolUses.map((t) => t.task?.state)).toEqual(["completed", "failed", "cancelled"])
  })

  it("returns the same array when no task runs", () => {
    const messages: Message[] = [{ role: "assistant", content: "", toolUses: [tool("completed")] }, { role: "user", content: "hi", toolUses: [] }]
    expect(settleStaleTasks(messages)).toBe(messages)
  })
})
