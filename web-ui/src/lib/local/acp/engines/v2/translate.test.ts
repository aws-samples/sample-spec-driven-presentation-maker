// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V2's notifications as LocalEvents, rule by rule (translate.ts): the load's replay is counted
 * and dropped; a sub-agent session reaches the chat only as the crew's group tools, in arrival
 * order, never with its text or chunks; the main session's text, tool chunks, calls (MCP tools
 * by `_meta.kiro.toolName`, built-ins by title) and completed results; the crew's call as one
 * composer start per stage; a steer injection; an MCP server's readiness.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

import { V2Translator } from "./translate"

const MAIN = "fa1545df"
const CHILD = "621f8fd1"

const update = (sessionId: string, u: Record<string, unknown>) => ({ method: "session/update", params: { sessionId, update: u } })
const kiroUpdate = (sessionId: string, u: Record<string, unknown>) => ({ method: "_kiro.dev/session/update", params: { sessionId, update: u } })
const text = (sessionId: string, t: string) => update(sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: t } })
const mcpCall = (sessionId: string, toolCallId: string, toolName: string) => update(sessionId, {
  sessionUpdate: "tool_call", toolCallId, title: `Running: @sdpm/${toolName}`, rawInput: { __tool_use_purpose: "p" },
  _meta: { kiro: { toolName, mcpServerName: "sdpm" } },
})
const completed = (sessionId: string, toolCallId: string, json?: string, extra: Record<string, unknown> = {}) => update(sessionId, {
  sessionUpdate: "tool_call_update", toolCallId, status: "completed", title: "Running: @sdpm/x",
  ...(json === undefined ? {} : { rawOutput: { items: [{ Json: { content: [{ type: "text", text: json }] } }] } }),
  ...extra,
})
const crewCall = (stages: Record<string, unknown>[]) => update(MAIN, {
  sessionUpdate: "tool_call", toolCallId: "crew", title: "Spawning agent crew",
  rawInput: { mode: "blocking", stages }, _meta: { kiro: { toolName: "subagent" } },
})

let t: V2Translator

beforeEach(() => {
  t = new V2Translator()
  t.mainSessionId = MAIN
  t.beginTurn()
})

describe("MCP readiness", () => {
  it("reports server_initialized as connected, for any session", () => {
    expect(t.translate({ method: "_kiro.dev/mcp/server_initialized", params: { sessionId: CHILD, serverName: "sdpm" } }))
      .toEqual([{ type: "mcp_status", sessionId: CHILD, server: "sdpm", state: "connected" }])
  })
})

describe("load replay", () => {
  it("drops the loaded session's updates until the load is answered, counting them", () => {
    const onReplay = vi.fn()
    t.startLoad("K9", onReplay)
    expect(t.translate(text("K9", "earlier"))).toEqual([])
    expect(t.translate(kiroUpdate("K9", { sessionUpdate: "tool_call_chunk", toolCallId: "x", title: "list_styles" }))).toEqual([])
    t.finishLoad(true)
    expect(onReplay.mock.calls).toEqual([[0, false], [1, false], [2, false], [2, true]])
    expect(t.mainSessionId).toBe("K9")
    expect(t.translate(text("K9", "now"))).toEqual([{ type: "text", text: "now" }])
  })

  it("keeps the main session when the load fails", () => {
    const onReplay = vi.fn()
    t.startLoad("K9", onReplay)
    t.finishLoad(false)
    expect(t.mainSessionId).toBe(MAIN)
    expect(onReplay.mock.calls).toEqual([[0, false]])
  })
})

describe("main session", () => {
  it("turns text into text and drops thoughts, plans and turn ends", () => {
    expect(t.translate(text(MAIN, "21"))).toEqual([{ type: "text", text: "21" }])
    expect(t.translate(update(MAIN, { sessionUpdate: "agent_thought_chunk", content: { type: "text", text: "hm" } }))).toEqual([])
    expect(t.translate(update(MAIN, { sessionUpdate: "plan", entries: [] }))).toEqual([])
    expect(t.translate(update(MAIN, { sessionUpdate: "turn_end" }))).toEqual([])
  })

  it("starts a tool on its chunk, the crew's as compose_slides", () => {
    expect(t.translate(kiroUpdate(MAIN, { sessionUpdate: "tool_call_chunk", toolCallId: "t1", title: "list_styles" })))
      .toEqual([{ type: "tool_start", id: "t1", name: "list_styles" }])
    expect(t.translate(kiroUpdate(MAIN, { sessionUpdate: "tool_call_chunk", toolCallId: "crew", title: "subagent" })))
      .toEqual([{ type: "tool_start", id: "crew", name: "compose_slides" }])
  })

  it("names an MCP tool by _meta.kiro.toolName and a built-in tool by its title", () => {
    expect(t.translate(mcpCall(MAIN, "t1", "list_styles"))).toEqual([{ type: "tool_use", id: "t1", name: "list_styles", input: { __tool_use_purpose: "p" } }])
    expect(t.translate(update(MAIN, { sessionUpdate: "tool_call", toolCallId: "t2", title: "Summarizing", _meta: { kiro: { toolName: "summary" } } })))
      .toEqual([{ type: "tool_use", id: "t2", name: "Summarizing", input: {} }])
  })

  it("ends a completed tool with its parsed result, and leaves other updates out", () => {
    t.translate(mcpCall(MAIN, "t1", "list_styles"))
    expect(t.translate(update(MAIN, { sessionUpdate: "tool_call_update", toolCallId: "t1", status: "in_progress" }))).toEqual([])
    expect(t.translate(completed(MAIN, "t1", "{\"styles\":[]}"))).toEqual([{ type: "tool_end", id: "t1", status: "success", result: { styles: [] } }])
    t.translate(mcpCall(MAIN, "t2", "x"))
    expect(t.translate(completed(MAIN, "t2", "not json"))).toEqual([{ type: "tool_end", id: "t2", status: "success", result: {} }])
    t.translate(mcpCall(MAIN, "t3", "x"))
    expect(t.translate(completed(MAIN, "t3", "21"))).toEqual([{ type: "tool_end", id: "t3", status: "success", result: {} }])
  })

  it("announces a completed tool no call announced, from the update's title", () => {
    expect(t.translate(completed(MAIN, "t9", undefined, { title: "Tool Load", rawInput: { tool_ids: ["a"] } }))).toEqual([
      { type: "tool_use", id: "t9", name: "Tool Load", input: { tool_ids: ["a"] } },
      { type: "tool_end", id: "t9", status: "success", result: {} },
    ])
  })

  it("reports a steer injection of the main session", () => {
    expect(t.translate(kiroUpdate(MAIN, { sessionUpdate: "AgentExecutionSteeringInjected", messageId: "steer-1", content: "stop" })))
      .toEqual([{ type: "steer_injected", messageId: "steer-1", content: "stop" }])
    expect(t.translate(kiroUpdate(CHILD, { sessionUpdate: "AgentExecutionSteeringInjected", content: "stop" }))).toEqual([])
  })
})

describe("crew and sub-agent sessions", () => {
  it("starts one composer group per stage", () => {
    expect(t.translate(crewCall([
      { name: "count-templates", role: "sdpm-composer", prompt_template: "slides: intro" },
      { name: "rest", role: "sdpm-composer" },
    ]))).toEqual([
      { type: "composer_start", group: "count-templates", prompt: "slides: intro", toolCallId: "crew" },
      { type: "composer_start", group: "rest", prompt: "rest", toolCallId: "crew" },
    ])
  })

  it("maps sub-agent sessions to the groups in arrival order and shows only their tools", () => {
    t.translate(crewCall([{ name: "a", prompt_template: "slides: one" }, { name: "b", prompt_template: "slides: two" }]))
    expect(t.translate(update("S2", { sessionUpdate: "agent_thought_chunk", content: { type: "text", text: "thinking" } }))).toEqual([])
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([{ type: "composer_tool", group: "b", id: "s1-t", name: "list_templates", input: { __tool_use_purpose: "p" } }])
    expect(t.translate(mcpCall("S2", "s2-t", "start_composing"))).toEqual([{ type: "composer_tool", group: "a", id: "s2-t", name: "start_composing", input: { __tool_use_purpose: "p" } }])
    expect(t.translate(completed("S1", "s1-t", "{}"))).toEqual([{ type: "composer_tool_end", group: "b", id: "s1-t", status: "success" }])
    expect(t.translate(update("S1", { sessionUpdate: "tool_call_update", toolCallId: "s1-u", status: "failed" }))).toEqual([{ type: "composer_tool_end", group: "b", id: "s1-u", status: "error" }])
    expect(t.translate(text("S1", "composer text"))).toEqual([])
    expect(t.translate(kiroUpdate("S1", { sessionUpdate: "tool_call_chunk", toolCallId: "s1-v", title: "summary" }))).toEqual([])
  })

  it("adds a group for a sub-agent session beyond the stages", () => {
    t.translate(crewCall([{ name: "a" }]))
    t.translate(text("S1", "x"))
    expect(t.translate(text("S2", "y"))).toEqual([{ type: "composer_start", group: "#2", prompt: "", toolCallId: "crew" }])
  })

  it("drops a sub-agent session's updates when no crew runs, and after the crew completed", () => {
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([])
    t.translate(crewCall([{ name: "a" }]))
    t.translate(completed(MAIN, "crew"))
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([])
  })

  it("names the sub-agent sessions of this turn for a cancel once each, until they send again", () => {
    t.translate(text("S1", "x"))
    t.translate(text("S2", "y"))
    expect(t.takeChildren()).toEqual(["S1", "S2"])
    expect(t.takeChildren()).toEqual([])
    t.translate(text("S2", "z"))
    expect(t.takeChildren()).toEqual(["S2"])
    t.endTurn()
    t.translate(text("S3", "after the turn"))
    expect(t.takeChildren()).toEqual([])
  })
})
