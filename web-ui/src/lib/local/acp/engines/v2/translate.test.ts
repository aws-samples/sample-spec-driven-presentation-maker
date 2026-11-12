// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V2's notifications as LocalEvents, rule by rule (translate.ts): the load's replay is counted
 * and dropped; a sub-agent session reaches the chat only as the tools of the crew group its
 * list_update `sessionName` maps it to, never with its text or chunks; a group ends when its
 * session terminated (success), stops otherwise (error) or the crew's call ends; the sessions
 * listed working are cancelled with the main one; the main session's text, tool chunks, calls
 * (MCP tools by `_meta.kiro.toolName`, built-ins by title) and completed or failed results; the
 * crew's call as one composer start per stage; a steer injection; an MCP server's readiness or
 * failure; a missing agent.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

import { V2Translator, v2McpEvents } from "./translate"

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

describe("MCP readiness and the agent", () => {
  it("reports server_initialized as connected and server_init_failure as failed, for any session, through v2McpEvents only", () => {
    const initialized = { method: "_kiro.dev/mcp/server_initialized", params: { sessionId: CHILD, serverName: "sdpm" } }
    const failed = { method: "_kiro.dev/mcp/server_init_failure", params: { sessionId: MAIN, serverName: "sdpm", error: "connection closed: initialize response" } }
    expect(v2McpEvents(initialized)).toEqual([{ type: "mcp_status", sessionId: CHILD, server: "sdpm", state: "connected" }])
    expect(v2McpEvents(failed)).toEqual([{ type: "mcp_status", sessionId: MAIN, server: "sdpm", state: "failed", error: "connection closed: initialize response" }])
    // A session id no translator knows yet (V2 sends it before the session/new answer) still counts.
    expect(v2McpEvents({ method: "_kiro.dev/mcp/server_initialized", params: { sessionId: "not-yet-known", serverName: "sdpm" } })).toHaveLength(1)
    expect(t.translate(initialized)).toEqual([])
    expect(t.translate(failed)).toEqual([])
    expect(v2McpEvents(text(MAIN, "hi"))).toEqual([])
  })

  it("logs agent/not_found and reports it to the mode check", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const seen = vi.fn()
      t.onAgentNotFound = seen
      const params = { sessionId: MAIN, requestedAgent: "sdpm-spec", fallbackAgent: "kiro_default" }
      expect(t.translate({ method: "_kiro.dev/agent/not_found", params })).toEqual([])
      expect(seen).toHaveBeenCalledWith(params)
      expect(warn).toHaveBeenCalledOnce()
    } finally {
      warn.mockRestore()
    }
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
    const end = { type: "tool_end", status: "success", name: "Running: @sdpm/x" }
    expect(t.translate(completed(MAIN, "t1", "{\"styles\":[]}"))).toEqual([{ ...end, id: "t1", result: { styles: [] } }])
    t.translate(mcpCall(MAIN, "t2", "x"))
    expect(t.translate(completed(MAIN, "t2", "not json"))).toEqual([{ ...end, id: "t2", result: {} }])
    t.translate(mcpCall(MAIN, "t3", "x"))
    expect(t.translate(completed(MAIN, "t3", "21"))).toEqual([{ ...end, id: "t3", result: {} }])
  })

  it("ends a failed tool with an error", () => {
    t.translate(mcpCall(MAIN, "t1", "list_styles"))
    expect(t.translate(update(MAIN, { sessionUpdate: "tool_call_update", toolCallId: "t1", status: "failed", title: "Running: @sdpm/list_styles" })))
      .toEqual([{ type: "tool_end", id: "t1", status: "error", result: {}, name: "Running: @sdpm/list_styles" }])
  })

  it("ends a completed tool no call announced as a result only, named by the update's title", () => {
    expect(t.translate(completed(MAIN, "t9", undefined, { title: "Tool Load", rawInput: { tool_ids: ["a"] } }))).toEqual([
      { type: "tool_end", id: "t9", status: "success", result: {}, name: "Tool Load" },
    ])
  })

  it("reports a steer injection of the main session", () => {
    expect(t.translate(kiroUpdate(MAIN, { sessionUpdate: "AgentExecutionSteeringInjected", messageId: "steer-1", content: "stop" })))
      .toEqual([{ type: "steer_injected", messageId: "steer-1", content: "stop" }])
    expect(t.translate(kiroUpdate(CHILD, { sessionUpdate: "AgentExecutionSteeringInjected", content: "stop" }))).toEqual([])
  })
})

describe("crew and sub-agent sessions", () => {
  const listed = (...subagents: [string, string, string][]) => ({
    method: "_kiro.dev/subagent/list_update",
    params: { subagents: subagents.map(([sessionId, sessionName, type]) => ({ sessionId, sessionName, agentName: "sdpm-composer", status: { type } })), pendingStages: [] },
  })
  const twoStages = () => t.translate(crewCall([{ name: "a", prompt_template: "slides: one" }, { name: "b", prompt_template: "slides: two" }]))

  it("starts one composer group per stage", () => {
    expect(t.translate(crewCall([
      { name: "count-templates", role: "sdpm-composer", prompt_template: "slides: intro" },
      { name: "rest", role: "sdpm-composer" },
    ]))).toEqual([
      { type: "composer_start", group: "count-templates", prompt: "slides: intro", toolCallId: "crew" },
      { type: "composer_start", group: "rest", prompt: "rest", toolCallId: "crew" },
    ])
  })

  it("maps sub-agent sessions to the groups by their list_update sessionName and shows only their tools", () => {
    twoStages()
    expect(t.translate(listed(["S1", "b", "working"], ["S2", "a", "working"]))).toEqual([])
    expect(t.translate(update("S2", { sessionUpdate: "agent_thought_chunk", content: { type: "text", text: "thinking" } }))).toEqual([])
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([{ type: "composer_tool", group: "b", id: "s1-t", name: "list_templates", input: { __tool_use_purpose: "p" } }])
    expect(t.translate(mcpCall("S2", "s2-t", "start_composing"))).toEqual([{ type: "composer_tool", group: "a", id: "s2-t", name: "start_composing", input: { __tool_use_purpose: "p" } }])
    expect(t.translate(completed("S1", "s1-t", "{}"))).toEqual([{ type: "composer_tool_end", group: "b", id: "s1-t", status: "success" }])
    expect(t.translate(update("S1", { sessionUpdate: "tool_call_update", toolCallId: "s1-u", status: "failed" }))).toEqual([{ type: "composer_tool_end", group: "b", id: "s1-u", status: "error" }])
    expect(t.translate(text("S1", "composer text"))).toEqual([])
    expect(t.translate(kiroUpdate("S1", { sessionUpdate: "tool_call_chunk", toolCallId: "s1-v", title: "summary" }))).toEqual([])
  })

  it("maps sessions of stages with the same name one each, in stage order", () => {
    t.translate(crewCall([{ name: "c" }, { name: "c" }]))
    t.translate(listed(["S1", "c", "working"], ["S2", "c", "working"]))
    expect(t.translate(mcpCall("S1", "s1-t", "x"))).toMatchObject([{ group: "c" }])
    expect(t.translate(mcpCall("S2", "s2-t", "x"))).toMatchObject([{ group: "#2" }])
  })

  it("drops the updates of a sub-agent session no group is mapped to", () => {
    twoStages()
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([])
    t.translate(listed(["S3", "other", "working"]))
    expect(t.translate(mcpCall("S3", "s3-t", "list_templates"))).toEqual([])
  })

  it("ends a group once when its session terminated, and failed on any other status but working", () => {
    twoStages()
    t.translate(listed(["S1", "a", "working"], ["S2", "b", "working"]))
    expect(t.translate(listed(["S1", "a", "terminated"], ["S2", "b", "working"]))).toEqual([{ type: "composer_end", group: "a", status: "success" }])
    expect(t.translate(listed(["S1", "a", "terminated"], ["S2", "b", "cancelled"]))).toEqual([{ type: "composer_end", group: "b", status: "error" }])
    expect(t.translate(listed(["S1", "a", "terminated"]))).toEqual([])
    expect(t.translate(listed())).toEqual([])
  })

  it("ends the groups still running with the crew's completed or failed update", () => {
    twoStages()
    t.translate(listed(["S1", "a", "terminated"]))
    expect(t.translate(completed(MAIN, "crew"))).toEqual([
      { type: "composer_end", group: "b", status: "success" },
      { type: "tool_end", id: "crew", status: "success", result: {}, name: "Running: @sdpm/x" },
    ])
    twoStages()
    expect(t.translate(update(MAIN, { sessionUpdate: "tool_call_update", toolCallId: "crew", status: "failed" }))).toEqual([
      { type: "composer_end", group: "a", status: "error" },
      { type: "composer_end", group: "b", status: "error" },
      { type: "tool_end", id: "crew", status: "error", result: {} },
    ])
  })

  it("drops a sub-agent session's updates when no crew runs, and after the crew completed", () => {
    t.translate(listed(["S1", "a", "working"]))
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([])
    t.translate(crewCall([{ name: "a" }]))
    t.translate(listed(["S1", "a", "working"]))
    t.translate(completed(MAIN, "crew"))
    expect(t.translate(mcpCall("S1", "s1-t", "list_templates"))).toEqual([])
    expect(t.translate(listed(["S1", "a", "terminated"]))).toEqual([])
  })

  it("names the sub-agent sessions the last list_update has working, for a cancel", () => {
    expect(t.workingChildren()).toEqual([])
    t.translate(listed(["S1", "a", "working"], ["S2", "b", "working"]))
    expect(t.workingChildren()).toEqual(["S1", "S2"])
    t.translate(listed(["S1", "a", "terminated"], ["S2", "b", "working"]))
    expect(t.workingChildren()).toEqual(["S2"])
    t.translate(listed())
    expect(t.workingChildren()).toEqual([])
  })
})
