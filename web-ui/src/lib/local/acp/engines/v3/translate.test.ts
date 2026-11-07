// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V3's notifications as LocalEvents, rule by rule (translate.ts): text and thoughts (replay,
 * sub-agent, main); tools (replay; delegations to the composer and to other agents; the internal
 * Tool Load and Subagent Response; tools inside a sub-agent; the main session's tools, named by
 * tool_id and read from rawInput.arguments, rawOutput.response or content[], a failure's
 * message, and an update with no call before it); the MCP snapshot; the steer injection; the
 * models of config_option_update; the custom agent notices.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

import { V3Translator } from "./translate"

const MAIN = "sess_main"
const COMPOSER = "sub-composer"
const STYLE = "sub-style"

const update = (u: Record<string, unknown>, sessionId = MAIN) => ({ method: "session/update", params: { sessionId, update: u } })
const kiro = (meta: Record<string, unknown>) => ({ _meta: { kiro: meta } })
const chunk = (kind: "agent_message_chunk" | "agent_thought_chunk", text: string, meta: Record<string, unknown> = {}) =>
  update({ sessionUpdate: kind, content: { type: "text", text }, ...kiro(meta) })
const mcpCall = (toolCallId: string, tool: string, meta: Record<string, unknown> = {}, args: Record<string, unknown> = { a: 1 }) => update({
  sessionUpdate: "tool_call", toolCallId, title: `@sdpm/${tool}`, kind: "other", status: "pending",
  rawInput: { tool_id: `sdpm::${tool}`, arguments: args }, ...kiro({ serverName: "sdpm", toolOrigin: "default", ...meta }),
})
const mcpDone = (toolCallId: string, tool: string, response: unknown, meta: Record<string, unknown> = {}, status = "completed") => update({
  sessionUpdate: "tool_call_update", toolCallId, status, title: `@sdpm/${tool}`,
  rawInput: { tool_id: `sdpm::${tool}`, arguments: {} }, rawOutput: response, ...kiro({ serverName: "sdpm", toolOrigin: "default", ...meta }),
})
const delegation = (toolCallId: string, subtask: string, name: string, status?: string) => update({
  sessionUpdate: status ? "tool_call_update" : "tool_call", toolCallId, title: `Sub-agent: ${name}`, status: status ?? "pending",
  rawInput: { name, prompt: `prompt for ${name}` }, ...(status === "completed" ? { rawOutput: "21" } : {}),
  ...kiro({ kind: "agent-subtask", agentSubtaskId: subtask }),
})
const toolLoad = (toolCallId: string, meta: Record<string, unknown> = {}) => update({
  sessionUpdate: "tool_call_update", toolCallId, status: "completed", title: "Tool Load",
  rawInput: { tool_ids: ["sdpm::list_styles"] }, rawOutput: { message: "{}" }, ...kiro({ toolOrigin: "default", ...meta }),
})
const subagentResponse = (toolCallId: string, subtask: string) => update({
  sessionUpdate: "tool_call_update", toolCallId, status: "completed", title: "Subagent Response",
  rawInput: { response: "4 templates", files: [] }, rawOutput: { message: "Response recorded." }, ...kiro({ agentSubtaskId: subtask, toolOrigin: "acp" }),
})

let t: V3Translator

beforeEach(() => {
  t = new V3Translator()
  t.mainSessionId = MAIN
})

describe("text and thoughts", () => {
  it("streams the main session's text and drops replayed text, thoughts and a sub-agent's text", () => {
    expect(t.translate(chunk("agent_message_chunk", "21"))).toEqual([{ type: "text", text: "21" }])
    expect(t.translate(chunk("agent_thought_chunk", "thinking"))).toEqual([])
    expect(t.translate(chunk("agent_message_chunk", "earlier", { replay: true }))).toEqual([])
    expect(t.translate(chunk("agent_message_chunk", "composer says", { agentSubtaskId: COMPOSER }))).toEqual([])
    expect(t.translate(chunk("agent_thought_chunk", "composer thinks", { agentSubtaskId: COMPOSER }))).toEqual([])
    expect(t.translate(update({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "x" } }, "sess_other"))).toEqual([])
  })
})

describe("load replay", () => {
  it("counts the replayed updates of the loaded session until the load is answered", () => {
    const onReplay = vi.fn()
    t.startLoad("sess_loaded", onReplay)
    expect(t.translate(update({ sessionUpdate: "user_message_chunk", content: { type: "text", text: "hi" }, ...kiro({ replay: true }) }, "sess_loaded"))).toEqual([])
    expect(t.translate(update({ ...mcpCall("t1", "list_styles").params.update, ...kiro({ serverName: "sdpm", replay: true }) }, "sess_loaded"))).toEqual([])
    t.finishLoad()
    expect(onReplay.mock.calls).toEqual([[0, false], [1, false], [2, false], [2, true]])
    expect(t.translate(chunk("agent_message_chunk", "now"))).toEqual([])
    expect(t.translate(update({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "now" } }, "sess_loaded"))).toEqual([{ type: "text", text: "now" }])
  })
})

describe("tools", () => {
  it("names a main MCP tool by tool_id, takes its input from rawInput.arguments and its result from rawOutput.response", () => {
    expect(t.translate(mcpCall("t1", "list_styles"))).toEqual([{ type: "tool_use", id: "t1", name: "list_styles", input: { a: 1 } }])
    expect(t.translate(mcpDone("t1", "list_styles", undefined, {}, "in_progress"))).toEqual([])
    expect(t.translate(mcpDone("t1", "list_styles", { response: "{\"styles\":[1]}" }))).toEqual([{ type: "tool_end", id: "t1", status: "success", result: { styles: [1] } }])
  })

  it("falls back to the title without @<server>/ and to {} without arguments; a built-in tool's input is rawInput", () => {
    const call = update({ sessionUpdate: "tool_call", toolCallId: "t1", title: "@sdpm/grid", rawInput: {}, ...kiro({ serverName: "sdpm" }) })
    expect(t.translate(call)).toEqual([{ type: "tool_use", id: "t1", name: "grid", input: {} }])
    const builtin = update({ sessionUpdate: "tool_call", toolCallId: "t2", title: "Read File", rawInput: { path: "/x" } })
    expect(t.translate(builtin)).toEqual([{ type: "tool_use", id: "t2", name: "Read File", input: { path: "/x" } }])
  })

  it("reads a result from content[] without a response, and keeps a non-JSON result empty", () => {
    t.translate(mcpCall("t1", "x"))
    const done = update({ sessionUpdate: "tool_call_update", toolCallId: "t1", status: "completed", content: [{ type: "content", content: { type: "text", text: "{\"ok\":true}" } }], ...kiro({ serverName: "sdpm" }) })
    expect(t.translate(done)).toEqual([{ type: "tool_end", id: "t1", status: "success", result: { ok: true } }])
    t.translate(mcpCall("t2", "x"))
    expect(t.translate(mcpDone("t2", "x", { response: "21" }))).toEqual([{ type: "tool_end", id: "t2", status: "success", result: {} }])
  })

  it("ends a failed tool with an error that carries rawOutput.message", () => {
    t.translate(mcpCall("t1", "list_styles"))
    expect(t.translate(mcpDone("t1", "list_styles", { message: "The user rejected this tool call." }, {}, "failed")))
      .toEqual([{ type: "tool_end", id: "t1", status: "error", result: { message: "The user rejected this tool call." } }])
  })

  it("announces a tool whose call never came from its finishing update, before ending it", () => {
    expect(t.translate(mcpDone("t9", "list_styles", { response: "{}" }))).toEqual([
      { type: "tool_use", id: "t9", name: "list_styles", input: {} },
      { type: "tool_end", id: "t9", status: "success", result: {} },
    ])
  })

  it("hides Tool Load and Subagent Response, from the main session and from a sub-agent", () => {
    expect(t.translate(toolLoad("l1"))).toEqual([])
    expect(t.translate(toolLoad("l2", { agentSubtaskId: COMPOSER }))).toEqual([])
    expect(t.translate(subagentResponse("r1", COMPOSER))).toEqual([])
  })

  it("makes a delegation to the composer a composer group, even though it carries its own agentSubtaskId", () => {
    expect(t.translate(delegation("d1", COMPOSER, "sdpm-composer"))).toEqual([
      { type: "composer_start", group: COMPOSER, prompt: "prompt for sdpm-composer", toolCallId: "d1" },
    ])
    expect(t.translate(delegation("d1", COMPOSER, "sdpm-composer", "in_progress"))).toEqual([])
    expect(t.translate(mcpCall("c1", "list_templates", { agentSubtaskId: COMPOSER }))).toEqual([
      { type: "composer_tool", group: COMPOSER, id: "c1", name: "list_templates", input: { a: 1 } },
    ])
    expect(t.translate(mcpDone("c1", "list_templates", { response: "{}" }, { agentSubtaskId: COMPOSER }, "in_progress"))).toEqual([])
    expect(t.translate(mcpDone("c1", "list_templates", { response: "{}" }, { agentSubtaskId: COMPOSER }))).toEqual([
      { type: "composer_tool_end", group: COMPOSER, id: "c1", status: "success" },
    ])
    expect(t.translate(delegation("d1", COMPOSER, "sdpm-composer", "completed"))).toEqual([{ type: "composer_end", group: COMPOSER, status: "success" }])
  })

  it("ends a failed delegation to the composer as failed", () => {
    t.translate(delegation("d1", COMPOSER, "sdpm-composer"))
    expect(t.translate(delegation("d1", COMPOSER, "sdpm-composer", "failed"))).toEqual([{ type: "composer_end", group: COMPOSER, status: "error" }])
  })

  it("shows a delegation to another agent as one plain card, without its inner tools", () => {
    expect(t.translate(delegation("d2", STYLE, "sdpm-style"))).toEqual([
      { type: "tool_use", id: "d2", name: "sdpm-style", input: { name: "sdpm-style", prompt: "prompt for sdpm-style" } },
    ])
    expect(t.translate(mcpCall("s1", "list_styles", { agentSubtaskId: STYLE }))).toEqual([])
    expect(t.translate(mcpDone("s1", "list_styles", { response: "{}" }, { agentSubtaskId: STYLE }))).toEqual([])
    expect(t.translate(delegation("d2", STYLE, "sdpm-style", "completed"))).toEqual([
      { type: "tool_end", id: "d2", status: "success", result: {}, name: "sdpm-style" },
    ])
  })

  it("drops tools of a sub-agent it never saw delegated", () => {
    expect(t.translate(mcpCall("x1", "list_styles", { agentSubtaskId: "unknown" }))).toEqual([])
  })
})

describe("other notifications", () => {
  it("turns an MCP status into a snapshot of the session's servers", () => {
    const status = (servers: unknown[]) => t.translate({ method: "_kiro/mcp/status", params: { sessionId: MAIN, servers } })
    expect(status([{ name: "sdpm", status: "connecting" }])).toEqual([
      { type: "mcp_snapshot", sessionId: MAIN },
      { type: "mcp_status", sessionId: MAIN, server: "sdpm", state: "connecting" },
    ])
    expect(status([{ name: "sdpm", status: "failed", errorMessage: "Connection closed" }, { name: "other", status: "connected" }])).toEqual([
      { type: "mcp_snapshot", sessionId: MAIN },
      { type: "mcp_status", sessionId: MAIN, server: "sdpm", state: "failed", error: "Connection closed" },
      { type: "mcp_status", sessionId: MAIN, server: "other", state: "connected" },
    ])
    expect(status([])).toEqual([{ type: "mcp_snapshot", sessionId: MAIN }])
  })

  it("reports a steer injection by its messageId and content", () => {
    expect(t.translate(update({ sessionUpdate: "session_info_update", ...kiro({ kind: "steering_injected", messageId: "steer-10", content: "first" }) })))
      .toEqual([{ type: "steer_injected", messageId: "steer-10", content: "first" }])
    expect(t.translate(update({ sessionUpdate: "session_info_update", title: "New title" }))).toEqual([])
  })

  it("keeps the models of the last config_option_update", () => {
    expect(t.models()).toBeNull()
    t.translate(update({ sessionUpdate: "config_option_update", configOptions: [
      { type: "select", id: "mode", category: "mode", currentValue: "sdpm-orchestrator", options: [{ value: "vibe", name: "Default" }] },
      { type: "select", id: "model", category: "model", currentValue: "auto", options: [
        { value: "auto", name: "Auto", description: "Models chosen by task" }, { value: "claude-sonnet-5.5", name: "Claude Sonnet 5.5" },
      ] },
    ] }))
    expect(t.models()).toEqual({ current: "auto", available: [
      { modelId: "auto", name: "Auto", description: "Models chosen by task" }, { modelId: "claude-sonnet-5.5", name: "Claude Sonnet 5.5" },
    ] })
  })

  it("logs a custom agent that was not started or not readable, and reports the former", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const seen = vi.fn()
      t.onAgentNotFound = seen
      const params = { sessionId: MAIN, requestedAgent: "sdpm-orchestrator", fallbackAgent: "vibe", skipped: { reasonCode: "cli_only_agent" } }
      expect(t.translate({ method: "_kiro/customAgent/not_found", params })).toEqual([])
      expect(t.translate({ method: "_kiro/customAgent/config_error", params: { path: "README.md", reasonCode: "invalid_config" } })).toEqual([])
      expect(seen).toHaveBeenCalledWith(params)
      expect(warn).toHaveBeenCalledTimes(2)
    } finally {
      warn.mockRestore()
    }
  })
})
