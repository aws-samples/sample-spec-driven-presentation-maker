// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * kiro-cli V3's extensions to ACP, as kiro-cli 3.0.0 / 3.1.0 (KAS 0.66.70) send them
 * (`kiro-cli acp --agent-engine v3`; captures in src/test/fixtures/acp/kiro-3.0.0-v3-*.jsonl).
 */
import type { LoadSessionResponse, NewSessionResponse, SessionCapabilities } from "../../schema"

/** The MCP servers of a session, as a full snapshot: `{sessionId, servers: [{name, status, errorMessage?}]}`. */
export const KIRO_MCP_STATUS = "_kiro/mcp/status"
/** The requested mode was not started and another runs: `{sessionId, requestedAgent, fallbackAgent, skipped}`. */
export const KIRO_CUSTOM_AGENT_NOT_FOUND = "_kiro/customAgent/not_found"
/** A file in an agents directory could not be read as an agent: `{sessionId, path, reasonCode, error}`. */
export const KIRO_CUSTOM_AGENT_CONFIG_ERROR = "_kiro/customAgent/config_error"

export interface V3McpServer {
  name?: string
  status?: string
  errorMessage?: string
}

export interface V3McpStatusParams {
  sessionId?: string
  servers?: V3McpServer[]
}

/** initialize's `agentCapabilities`: V3 advertises fork next to ACP's session capabilities, and its own in `_meta.kiro`. */
export interface V3AgentCapabilities {
  sessionCapabilities?: SessionCapabilities & { fork?: Record<string, unknown> | null }
  _meta?: { kiro?: { replayMarking?: boolean; extensionMethods?: string[] } } | null
}

/** session/new and session/load answer the session's record in `_meta`; `createdAt` is ISO 8601. */
export interface V3SessionMeta {
  id?: string
  createdAt?: string
  agentMode?: string
  /** A fork's source (session/load of a fork, kiro-cli 3.1). */
  parentSessionId?: string
}

/** `_meta.kiro` of a session/list row (kiro-cli 3.1.0). */
export interface V3SessionInfoMeta {
  agentMode?: string
  modeId?: string
  createdAt?: string
  /** `idle`, or `busy` while another kiro-cli has it open. */
  status?: string
  parentSessionId?: string
}

/** session/list's `_meta.kiro`: `filter.workflowSessions: "exclude"` leaves out the sessions of kiro workflows. */
export interface V3ListSessionsMeta {
  kiro: { filter: { workflowSessions: "exclude" | "include" } }
}

export type V3NewSessionResponse = NewSessionResponse & { _meta?: V3SessionMeta | null }
export type V3LoadSessionResponse = LoadSessionResponse & { _meta?: V3SessionMeta | null }

/**
 * `_meta.kiro` of an update:
 * - `replay`: replayed by session/load.
 * - `kind: "agent-subtask"`: a delegation to a sub-agent (`rawInput {name, prompt}`), with its
 *   own `agentSubtaskId`; updates from inside a sub-agent carry its `agentSubtaskId`.
 * - `serverName`: the MCP server of a tool call (`rawInput {tool_id: "<server>::<tool>", arguments}`).
 * - `toolOrigin: "acp"`: the sub-agent's answer to its parent ("Subagent Response").
 * - `kind: "steering_injected"` (session_info_update): kiro-cli put a steer into the turn.
 */
export interface V3UpdateMeta {
  replay?: boolean
  kind?: string
  agentSubtaskId?: string
  serverName?: string
  toolOrigin?: string
  messageId?: string
  content?: string
}

/** A delegation's input. */
export interface V3SubtaskInput {
  name?: string
  prompt?: string
}

/** An MCP tool call's input, as V3 wraps it. */
export interface V3ToolInput {
  tool_id?: string
  arguments?: Record<string, unknown>
  /** Only on the internal tool-loading call ("Tool Load"). */
  tool_ids?: string[]
}

/** A finished tool call's output: an MCP result in `response` (JSON text), a failure in `message`. */
export interface V3ToolOutput {
  response?: string
  message?: string
}

/** A model's `_meta.kiro` in the model option: its credit multiplier and, with `hasEffort`, its effort levels. */
export interface V3ModelMeta {
  rateMultiplier?: number
  hasEffort?: boolean
  effortLevels?: string[]
  defaultEffortLevel?: string
}

/**
 * A `config_option_update` option of type select. The model list is the one with category
 * `model`; a model with effort adds one with category `thought_level` (its levels, current = the
 * model's default) and one with category `thinking`, which a model without effort removes.
 */
export interface V3SelectOption {
  id?: string
  category?: string
  currentValue?: string
  options?: { value?: string; name?: string; description?: string; _meta?: { kiro?: V3ModelMeta } | null }[]
}
