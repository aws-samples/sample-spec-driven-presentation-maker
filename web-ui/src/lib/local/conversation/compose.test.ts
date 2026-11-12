// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Compose card (compose.ts), the same for every engine: the first batch of composer starts
 * opens one card under the delegation's tool call; a start while it is open adds a group in
 * arrival order, `total_groups` the count so far; a group's tools stream under the card and its
 * end reports done or error; the card closes once every group ended, and a later start opens a
 * new one; the delegation's own tool end adds nothing; the end of the turn (any stopReason, a
 * Stop, an error) closes an open card with its unfinished groups failed. Slugs come from the
 * prompt's `assigned_slugs:` line (JSON list or comma-separated) or a legacy `slides:`, "group N"
 * without any. A compose task's card (`TaskCards`, the background run's) survives the turn's
 * begin and end; the conversation hands the run's tool calls and ends over (by the `tool_use`
 * name) and shows no tool result for those ends.
 */

import { describe, expect, it } from "vitest"

import { ComposeTracker, promptSlugs, TaskCards } from "./compose"
import type { ChatEvent, LocalEvent } from "./events"
import { ConversationState } from "./index"

const start = (group: string, prompt: string, toolCallId = "crew"): Extract<LocalEvent, { type: "composer_start" }> =>
  ({ type: "composer_start", group, prompt, toolCallId })
const payloads = (events: ChatEvent[]) => events.map((e) => e.payload)
const stream = (data: Record<string, unknown>, toolUseId = "crew") => ({ toolStream: { toolUseId, name: "compose_slides", data } })
const closed = (status: "success" | "error", toolUseId = "crew") => ({ toolResult: { toolUseId, name: "compose_slides", status, content: "{}" } })

describe("promptSlugs", () => {
  it.each([
    ["deck_id: d1\nassigned_slugs: [\"intro\", \"agenda\"]\nmode: pptx", ["intro", "agenda"]],
    ["deck_id: d1\nassigned_slugs: intro, agenda\nmode: pptx", ["intro", "agenda"]],
    ["assigned_slugs: ['intro', 'agenda']", ["intro", "agenda"]],
    ["Build slides: intro, agenda.", ["intro", "agenda"]],
    ["slide: summary\nmore", ["summary"]],
    ["no slugs here", []],
    ["assigned_slugs: []", []],
  ])("reads %j", (prompt, slugs) => {
    expect(promptSlugs(prompt)).toEqual(slugs)
  })
})

describe("ComposeTracker", () => {
  it("opens one card from a batch of starts, then reports each group starting", () => {
    const tracker = new ComposeTracker()
    expect(payloads(tracker.start([start("a", "assigned_slugs: [\"intro\", \"agenda\"]"), start("b", "Write the rest")]))).toEqual([
      { toolUse: { toolUseId: "crew", name: "compose_slides", input: { slide_groups: [
        { slugs: ["intro", "agenda"], instruction: "assigned_slugs: [\"intro\", \"agenda\"]" },
        { slugs: [], instruction: "Write the rest" },
      ] } } },
      stream({ group: 1, total_groups: 2, slugs: "intro, agenda", status: "starting" }),
      stream({ group: 2, total_groups: 2, slugs: "group 2", status: "starting" }),
    ])
    expect(tracker.isDelegation("crew")).toBe(true)
  })

  it("streams a group's tools under the card", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("a", "slides: intro")])
    expect(payloads(tracker.tool("a", "t1", "list_templates"))).toEqual([stream({ group: 1, slugs: "intro", tool: "list_templates", toolUseId: "t1" })])
    expect(payloads(tracker.toolEnd("a", "t1", "error"))).toEqual([stream({ group: 1, slugs: "intro", toolResult: "t1", toolStatus: "error" })])
    expect(payloads(tracker.tool("unknown", "t2", "x"))).toEqual([])
  })

  it("one group: its end reports done and closes the card", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("a", "assigned_slugs: intro")])
    expect(payloads(tracker.groupEnd("a", "success"))).toEqual([
      stream({ group: 1, slugs: "intro", status: "done" }),
      closed("success"),
    ])
    expect(payloads(tracker.groupEnd("a", "success"))).toEqual([])
    expect(payloads(tracker.tool("a", "t3", "x"))).toEqual([])
    expect(payloads(tracker.endTurn())).toEqual([])
  })

  it("two groups in parallel: one card, numbered in arrival order, closed when both ended", () => {
    const tracker = new ComposeTracker()
    expect(payloads(tracker.start([start("s1", "assigned_slugs: [\"a\"]", "d1")]))).toEqual([
      { toolUse: { toolUseId: "d1", name: "compose_slides", input: { slide_groups: [{ slugs: ["a"], instruction: "assigned_slugs: [\"a\"]" }] } } },
      stream({ group: 1, total_groups: 1, slugs: "a", status: "starting" }, "d1"),
    ])
    expect(payloads(tracker.start([start("s2", "assigned_slugs: [\"b\"]", "d2")]))).toEqual([
      stream({ group: 2, total_groups: 2, slugs: "b", status: "starting" }, "d1"),
    ])
    expect(tracker.isDelegation("d2")).toBe(true)
    expect(payloads(tracker.groupEnd("s2", "success"))).toEqual([stream({ group: 2, slugs: "b", status: "done" }, "d1")])
    expect(payloads(tracker.groupEnd("s1", "success"))).toEqual([stream({ group: 1, slugs: "a", status: "done" }, "d1"), closed("success", "d1")])
  })

  it("two passes: a start after the card closed opens a new card", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("layout", "assigned_slugs: a, b", "d1")])
    tracker.groupEnd("layout", "success")
    const second = payloads(tracker.start([start("content", "assigned_slugs: a", "d2")]))
    expect(second[0]).toEqual({ toolUse: { toolUseId: "d2", name: "compose_slides", input: { slide_groups: [{ slugs: ["a"], instruction: "assigned_slugs: a" }] } } })
    expect(second[1]).toEqual(stream({ group: 1, total_groups: 1, slugs: "a", status: "starting" }, "d2"))
  })

  it("closes with an error when a group failed", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("a", ""), start("b", "")])
    tracker.groupEnd("a", "error")
    expect(payloads(tracker.groupEnd("b", "success"))).toEqual([stream({ group: 2, slugs: "group 2", status: "done" }), closed("error")])
  })

  it("the end of the turn closes an open card and fails the groups that did not end", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("a", "slides: one"), start("b", "slides: two")])
    tracker.groupEnd("a", "success")
    expect(payloads(tracker.endTurn())).toEqual([stream({ group: 2, slugs: "two", status: "error" }), closed("error")])
    expect(payloads(tracker.endTurn())).toEqual([])
  })
})

describe("ConversationState", () => {
  const crew = (conversation: ConversationState) => conversation.apply([
    { type: "composer_start", group: "a", prompt: "slides: intro", toolCallId: "crew" },
    { type: "composer_start", group: "b", prompt: "slides: outro", toolCallId: "crew" },
  ])

  it("takes one notification's composer starts as one batch", () => {
    const opened = crew(new ConversationState())
    expect(opened.events.filter((e) => e.payload && "toolUse" in e.payload)).toHaveLength(1)
    expect(opened.events).toHaveLength(3)
  })

  it("V2 crew completed: the remaining groups succeed and close the card; the crew's tool end adds nothing", () => {
    const conversation = new ConversationState()
    crew(conversation)
    const ended = conversation.apply([
      { type: "composer_end", group: "a", status: "success" },
      { type: "composer_end", group: "b", status: "success" },
      { type: "tool_end", id: "crew", status: "success", result: {} },
    ])
    expect(payloads(ended.events)).toEqual([
      stream({ group: 1, slugs: "intro", status: "done" }),
      stream({ group: 2, slugs: "outro", status: "done" }),
      closed("success"),
    ])
  })

  it("V2 crew failed: the remaining groups fail and the card closes with an error", () => {
    const conversation = new ConversationState()
    crew(conversation)
    conversation.apply([{ type: "composer_end", group: "a", status: "success" }])
    const ended = conversation.apply([
      { type: "composer_end", group: "b", status: "error" },
      { type: "tool_end", id: "crew", status: "error", result: {} },
    ])
    expect(payloads(ended.events)).toEqual([stream({ group: 2, slugs: "outro", status: "error" }), closed("error")])
  })

  it("the end of the turn closes a card still open, the running groups failed", () => {
    const conversation = new ConversationState()
    crew(conversation)
    conversation.apply([{ type: "composer_end", group: "a", status: "success" }])
    expect(payloads(conversation.endTurn())).toEqual([stream({ group: 2, slugs: "outro", status: "error" }), closed("error")])
  })

  it("starts each turn without the last turn's card", () => {
    const conversation = new ConversationState()
    conversation.apply([{ type: "composer_start", group: "a", prompt: "", toolCallId: "crew" }])
    conversation.beginTurn()
    expect(conversation.apply([{ type: "composer_tool", group: "a", id: "t1", name: "x" }]).events).toEqual([])
    expect(conversation.endTurn()).toEqual([])
  })
})

describe("task cards", () => {
  it("stream under the dispatch's id and survive the turn's begin and end", () => {
    const state = new ConversationState()
    state.tasks.open("disp", [{ slugs: ["a", "b"] }, { slugs: ["c"] }])
    state.beginTurn()
    expect(state.endTurn()).toEqual([])
    expect(payloads(state.tasks.starting("disp", 2))).toEqual([stream({ group: 2, total_groups: 2, slugs: "c", status: "starting" }, "disp")])
    expect(payloads(state.tasks.tool("disp", 1, "t1", "run_python"))).toEqual([stream({ group: 1, slugs: "a, b", tool: "run_python", toolUseId: "t1" }, "disp")])
    expect(payloads(state.tasks.toolEnd("disp", 1, "t1", "success"))).toEqual([stream({ group: 1, slugs: "a, b", toolResult: "t1", toolStatus: "success" }, "disp")])
    expect(payloads(state.tasks.groupEnd("disp", 1, "done"))).toEqual([stream({ group: 1, slugs: "a, b", status: "done" }, "disp")])
    state.tasks.close("disp")
    expect(state.tasks.groupEnd("disp", 2, "error")).toEqual([])
    expect(new TaskCards().starting("none", 1)).toEqual([])
  })

  it("leaves a delegation card's turn-end close as it was", () => {
    const state = new ConversationState()
    state.tasks.open("disp", [{ slugs: ["a"] }])
    state.apply([start("g1", "assigned_slugs: x")])
    expect(payloads(state.endTurn())).toEqual([stream({ group: 1, slugs: "x", status: "error" }), closed("error")])
    expect(state.tasks.has("disp")).toBe(true)
  })
})

describe("the compose run's tools", () => {
  const use = (id: string, name: string, input: Record<string, unknown> = {}): LocalEvent => ({ type: "tool_use", id, name, input })
  const end = (id: string, name?: string): LocalEvent => ({ type: "tool_end", id, status: "success", result: { status: "dispatched" }, ...(name ? { name } : {}) })

  it("hands compose_slides and message_composer ends over without a tool result, by the tool_use's name", () => {
    const state = new ConversationState()
    // tool_use and tool_end in one notification (V3 announces a call at its end); a nameless V3 end; a titled V2 end.
    const out = state.apply([use("c1", "compose_slides", { deck_id: "/d" }), end("c1"), use("m1", "message_composer", { group: 1, text: "hi" }), end("m1", "Running: @sdpm/message_composer")])
    expect(payloads(out.events)).toEqual([
      { toolUse: { toolUseId: "c1", name: "compose_slides", input: { deck_id: "/d" } } },
      { toolUse: { toolUseId: "m1", name: "message_composer", input: { group: 1, text: "hi" } } },
    ])
    expect(out.runToolUses.map((u) => u.id)).toEqual(["c1", "m1"])
    expect(out.runToolEnds).toEqual([
      { id: "c1", name: "compose_slides", status: "success", result: { status: "dispatched" } },
      { id: "m1", name: "message_composer", status: "success", result: { status: "dispatched" } },
    ])
    expect(state.toolNameOf("c1")).toBe("compose_slides")
    expect(payloads(state.toolResult("c1", "error", { message: "no" }).events)).toEqual([{ toolResult: { toolUseId: "c1", name: "compose_slides", status: "error", content: JSON.stringify({ message: "no" }) } }])
  })

  it("shows other tools as before, also a tool_end named compose_slides whose tool_use had another name", () => {
    const state = new ConversationState()
    const out = state.apply([use("x1", "list_styles"), end("x1", "compose_slides"), end("x2", "compose_slides")])
    expect(out.runToolUses).toEqual([])
    expect(out.runToolEnds).toEqual([])
    expect(payloads(out.events).map((p) => Object.keys(p ?? {})[0])).toEqual(["toolUse", "toolResult", "toolResult"])
  })
})
