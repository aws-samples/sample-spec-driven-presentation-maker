// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Compose card: the first batch of composer starts opens one card under the delegation's
 * tool call with all its groups, each group then reports `starting`; a start while the card is
 * open adds a group in arrival order; a group's tools stream under the card; the delegation's
 * tool end closes it. Slugs come from the group's prompt, "group N" without any.
 */

import { describe, expect, it } from "vitest"

import { ComposeTracker, extractSlugs } from "./compose"
import type { ChatEvent, LocalEvent } from "./events"
import { ConversationState } from "./index"

const start = (group: string, prompt: string, toolCallId = "crew"): Extract<LocalEvent, { type: "composer_start" }> =>
  ({ type: "composer_start", group, prompt, toolCallId })
const payloads = (events: ChatEvent[]) => events.map((e) => e.payload)
const stream = (data: Record<string, unknown>) => ({ toolStream: { toolUseId: "crew", name: "compose_slides", data } })

describe("extractSlugs", () => {
  it.each([
    ["Build slides: intro, agenda.", "intro, agenda"],
    ["slide: summary\nmore", "summary"],
    ["no slugs here", ""],
  ])("reads %j", (prompt, slugs) => {
    expect(extractSlugs(prompt)).toBe(slugs)
  })
})

describe("ComposeTracker", () => {
  it("opens one card from a batch of starts, then reports each group starting", () => {
    const tracker = new ComposeTracker()
    expect(payloads(tracker.start([start("a", "Build slides: intro, agenda."), start("b", "Write the rest")]))).toEqual([
      { toolUse: { toolUseId: "crew", name: "compose_slides", input: { slide_groups: [
        { slugs: ["intro", "agenda"], instruction: "Build slides: intro, agenda." },
        { slugs: [], instruction: "Write the rest" },
      ] } } },
      stream({ group: 1, total_groups: 2, slugs: "intro, agenda", status: "starting" }),
      stream({ group: 2, total_groups: 2, slugs: "group 2", status: "starting" }),
    ])
    expect(tracker.toolUseId).toBe("crew")
  })

  it("adds a start that comes while the card is open as the next group", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("a", "slides: intro")])
    expect(payloads(tracker.start([start("b", "", "other")]))).toEqual([stream({ group: 2, total_groups: 2, slugs: "group 2", status: "starting" })])
  })

  it("streams a group's tools under the card and closes it with the delegation's result", () => {
    const tracker = new ComposeTracker()
    tracker.start([start("a", "slides: intro")])
    expect(payloads(tracker.tool("a", "t1", "list_templates"))).toEqual([stream({ group: 1, slugs: "intro", tool: "list_templates", toolUseId: "t1" })])
    expect(payloads(tracker.toolEnd("a", "t1", "error"))).toEqual([stream({ group: 1, slugs: "intro", toolResult: "t1", toolStatus: "error" })])
    expect(payloads(tracker.tool("unknown", "t2", "x"))).toEqual([])
    expect(payloads(tracker.end("success", {}))).toEqual([{ toolResult: { toolUseId: "crew", name: "compose_slides", status: "success", content: "{}" } }])
    expect(tracker.toolUseId).toBeNull()
    expect(payloads(tracker.tool("a", "t3", "x"))).toEqual([])
  })
})

describe("ConversationState", () => {
  it("takes one notification's composer starts as one batch, and closes the card on the delegation's tool end", () => {
    const conversation = new ConversationState()
    const opened = conversation.apply([
      { type: "composer_start", group: "a", prompt: "slides: intro", toolCallId: "crew" },
      { type: "composer_start", group: "b", prompt: "slides: outro", toolCallId: "crew" },
    ])
    expect(opened.events.filter((e) => e.payload && "toolUse" in e.payload)).toHaveLength(1)
    expect(opened.events).toHaveLength(3)
    const closed = conversation.apply([{ type: "tool_end", id: "crew", status: "success", result: {} }])
    expect(payloads(closed.events)).toEqual([{ toolResult: { toolUseId: "crew", name: "compose_slides", status: "success", content: "{}" } }])
  })

  it("starts each turn without the last turn's card", () => {
    const conversation = new ConversationState()
    conversation.apply([{ type: "composer_start", group: "a", prompt: "", toolCallId: "crew" }])
    conversation.beginTurn()
    expect(conversation.apply([{ type: "composer_tool", group: "a", id: "t1", name: "x" }]).events).toEqual([])
  })
})
