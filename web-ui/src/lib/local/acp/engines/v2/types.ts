// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * kiro-cli V2's extensions to ACP, as kiro-cli 3.0.0 sends them (`kiro-cli acp --agent <name>`;
 * captures in src/test/fixtures/acp/kiro-3.0.0-v2-*.jsonl).
 */
import type { AcpModel } from "../../engine"
import type { NewSessionResponse, ToolCall, ToolCallUpdate } from "../../schema"

/** V2's own update channel: tool call chunks and steer injections. */
export const KIRO_SESSION_UPDATE = "_kiro.dev/session/update"
/** An MCP server of a session finished starting: `{sessionId, serverName}`. */
export const KIRO_MCP_SERVER_INITIALIZED = "_kiro.dev/mcp/server_initialized"

/** session/new also answers the models the agent offers. */
export interface V2NewSessionResponse extends NewSessionResponse {
  models?: { currentModelId?: string; availableModels?: AcpModel[] }
}

/** `_meta.kiro` of a tool_call: MCP tools name their server; the crew is toolName "subagent". */
export interface V2ToolMeta {
  toolName?: string
  mcpServerName?: string
}

/** The crew tool call's input: one stage per composer group. */
export interface V2CrewInput {
  stages?: { name?: string; role?: string; prompt_template?: string }[]
}

/** A finished MCP tool call's output. */
export interface V2ToolOutput {
  items?: { Json?: { content?: { text?: string }[] } }[]
}

/** Updates on `_kiro.dev/session/update`. */
export type V2KiroUpdate =
  /** A tool call announced before its input; `title` is the tool's name. */
  | { sessionUpdate: "tool_call_chunk"; toolCallId: string; title?: string; kind?: string }
  /** kiro-cli put a steer into the running turn. */
  | { sessionUpdate: "AgentExecutionSteeringInjected"; messageId?: string; content?: string }

export type V2ToolCall = ToolCall & { _meta?: { kiro?: V2ToolMeta } | null }
export type V2ToolCallUpdate = ToolCallUpdate
