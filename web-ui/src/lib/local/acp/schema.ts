// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Agent Client Protocol types this client uses, copied from the ACP schema
 * (agentclientprotocol/agent-client-protocol, `schema/v1/schema.json`, tag `schema-v1.29.1`,
 * protocol version 1). Types only: the transport and the engine adapters read these shapes.
 *
 * Kiro's extensions (`_meta.kiro`, its own notification methods, extra response fields) are not here;
 * each engine adapter keeps the shapes it reads in its own folder (`engines/<id>/types.ts`).
 */

/** `_meta` is reserved by ACP for extension data; implementations put their own keys in it. */
export type AcpMeta = Record<string, unknown> | null

export interface Implementation {
  name: string
  title?: string | null
  version: string
  _meta?: AcpMeta
}

export interface PromptCapabilities {
  image?: boolean
  audio?: boolean
  embeddedContext?: boolean
  _meta?: AcpMeta
}

export interface McpCapabilities {
  http?: boolean
  sse?: boolean
  _meta?: AcpMeta
}

/** Each capability is advertised by an object (`{}`), and not advertised when omitted or null. */
export interface SessionCapabilities {
  list?: Record<string, unknown> | null
  delete?: Record<string, unknown> | null
  additionalDirectories?: Record<string, unknown> | null
  resume?: Record<string, unknown> | null
  close?: Record<string, unknown> | null
  _meta?: AcpMeta
}

export interface AgentCapabilities {
  loadSession?: boolean
  promptCapabilities?: PromptCapabilities
  mcpCapabilities?: McpCapabilities
  sessionCapabilities?: SessionCapabilities
  auth?: Record<string, unknown>
  _meta?: AcpMeta
}

export interface InitializeResponse {
  protocolVersion: number
  agentCapabilities?: AgentCapabilities
  authMethods?: unknown[]
  agentInfo?: Implementation | null
  _meta?: AcpMeta
}

export interface SessionMode {
  id: string
  name: string
  description?: string | null
  _meta?: AcpMeta
}

export interface SessionModeState {
  currentModeId: string
  availableModes: SessionMode[]
  _meta?: AcpMeta
}

export interface SessionConfigOption {
  id: string
  name: string
  description?: string | null
  category?: string | null
  type?: string
  _meta?: AcpMeta
}

export interface NewSessionResponse {
  sessionId: string
  modes?: SessionModeState | null
  configOptions?: SessionConfigOption[] | null
  _meta?: AcpMeta
}

export interface LoadSessionResponse {
  modes?: SessionModeState | null
  configOptions?: SessionConfigOption[] | null
  _meta?: AcpMeta
}

/** One session of session/list. */
export interface SessionInfo {
  sessionId: string
  cwd: string
  title?: string | null
  /** ISO 8601 */
  updatedAt?: string | null
  _meta?: AcpMeta
}

export interface ListSessionsRequest {
  cwd?: string | null
  cursor?: string | null
  _meta?: AcpMeta
}

export interface ListSessionsResponse {
  sessions: SessionInfo[]
  nextCursor?: string | null
  _meta?: AcpMeta
}

/** session/fork is unstable in ACP (`sessionCapabilities.fork`, not in the stable schema yet). */
export interface ForkSessionRequest {
  sessionId: string
  cwd: string
  mcpServers: unknown[]
  _meta?: AcpMeta
}

export interface ForkSessionResponse {
  sessionId: string
  modes?: SessionModeState | null
  configOptions?: SessionConfigOption[] | null
  _meta?: AcpMeta
}

export interface DeleteSessionRequest {
  sessionId: string
  _meta?: AcpMeta
}

export interface TextContent {
  type: "text"
  text: string
  _meta?: AcpMeta
}

/** A content block; only text is read here, the other kinds are not shown. */
export type ContentBlock = TextContent | { type: "image" | "audio" | "resource_link" | "resource"; [key: string]: unknown }

export interface ContentChunk {
  content: ContentBlock
  messageId?: string | null
  _meta?: AcpMeta
}

export type ToolKind = "read" | "edit" | "delete" | "move" | "search" | "execute" | "think" | "fetch" | "switch_mode" | "other"

export type ToolCallStatus = "pending" | "in_progress" | "completed" | "failed"

export interface ToolCall {
  toolCallId: string
  title: string
  name?: string | null
  kind?: ToolKind
  status?: ToolCallStatus
  content?: unknown[]
  locations?: unknown[]
  rawInput?: unknown
  rawOutput?: unknown
  _meta?: AcpMeta
}

export interface ToolCallUpdate {
  toolCallId: string
  kind?: ToolKind | null
  status?: ToolCallStatus | null
  title?: string | null
  name?: string | null
  content?: unknown[] | null
  locations?: unknown[] | null
  rawInput?: unknown
  rawOutput?: unknown
  _meta?: AcpMeta
}

export interface SessionInfoUpdate {
  title?: string | null
  updatedAt?: string | null
  _meta?: AcpMeta
}

export interface ConfigOptionUpdate {
  configOptions: SessionConfigOption[]
  _meta?: AcpMeta
}

/** The `session/update` kinds this client reads; the others (plan, usage, ...) are ignored. */
export type SessionUpdate =
  | ({ sessionUpdate: "agent_message_chunk" } & ContentChunk)
  | ({ sessionUpdate: "agent_thought_chunk" } & ContentChunk)
  | ({ sessionUpdate: "tool_call" } & ToolCall)
  | ({ sessionUpdate: "tool_call_update" } & ToolCallUpdate)
  | ({ sessionUpdate: "session_info_update" } & SessionInfoUpdate)
  | ({ sessionUpdate: "config_option_update" } & ConfigOptionUpdate)

export interface SessionNotification {
  sessionId: string
  update: SessionUpdate
  _meta?: AcpMeta
}

export type PermissionOptionKind = "allow_once" | "allow_always" | "reject_once" | "reject_always"

export interface PermissionOption {
  optionId: string
  name: string
  kind: PermissionOptionKind
  _meta?: AcpMeta
}

export interface RequestPermissionRequest {
  sessionId: string
  toolCall: ToolCallUpdate
  options: PermissionOption[]
  _meta?: AcpMeta
}

export type RequestPermissionOutcome = { outcome: "cancelled" } | { outcome: "selected"; optionId: string }

export interface RequestPermissionResponse {
  outcome: RequestPermissionOutcome
  _meta?: AcpMeta
}

export type StopReason = "end_turn" | "max_tokens" | "max_turn_requests" | "refusal" | "cancelled"

export interface PromptResponse {
  stopReason: StopReason
  _meta?: AcpMeta
}

/** A JSON-RPC error object, as ACP answers a failed request. */
export interface AcpError {
  code: number
  message: string
  data?: unknown
}

/** A notification from the agent (a JSON-RPC message with a method and no id). */
export interface AcpNotification {
  method: string
  params?: unknown
}
