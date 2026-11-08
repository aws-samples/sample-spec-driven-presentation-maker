// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The two event vocabularies of a Local chat, engine-independent.
 *
 * - `LocalEvent`: what an engine adapter (`acp/engines/<id>/translate.ts`) makes of one kiro-cli
 *   notification. Notifications of the main session and of a sub-agent session keep the session
 *   they came in. `mcp_status` / `mcp_snapshot` go to the host's MCP readiness watch (hosts.ts),
 *   everything else to the conversation model (`ConversationState`).
 * - `ChatEvent`: what the conversation model makes of them for the chat, buffered and numbered by
 *   the chat (chat.ts, per work period) and written by the SSE bridge as `id: <n>` + `data: <payload>`. `SsePayload`
 *   is the union of the payload shapes the chat UI reads (strandsParser, ComposeCard, the steer
 *   and notice handling); an `end` event closes the stream, after its payload if it has one.
 */
import type { LocalSessionNoticeCode } from "../sessionNotices"
import type { LocalTurnErrorCode } from "../turnErrors"

export type ToolEndStatus = "success" | "error"

export type LocalEvent =
  | { type: "text"; text: string }
  /** A tool call announced before its input (V2's tool_call_chunk). */
  | { type: "tool_start"; id: string; name: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  /** `name`: the tool's name its own update gives, shown when no call announced the tool. */
  | { type: "tool_end"; id: string; status: ToolEndStatus; result: Record<string, unknown>; name?: string }
  /** One group of a delegation to the composer; `toolCallId` is the delegation's tool call. */
  | { type: "composer_start"; group: string; prompt: string; toolCallId: string }
  | { type: "composer_tool"; group: string; id: string; name: string; input?: Record<string, unknown> }
  | { type: "composer_tool_end"; group: string; id: string; status: ToolEndStatus }
  /** The group's composer finished (`success`) or stopped without finishing (`error`). */
  | { type: "composer_end"; group: string; status: ToolEndStatus }
  /** kiro-cli put a steer into the running turn (matched by its messageId, else by its text). */
  | { type: "steer_injected"; messageId?: string; content?: string }
  | { type: "mcp_status"; sessionId: string; server: string; state: "connecting" | "connected" | "failed"; error?: string }
  /** Clears what is recorded for the session's MCP servers (a full snapshot follows). */
  | { type: "mcp_snapshot"; sessionId: string }

export type McpStatusEvent = Extract<LocalEvent, { type: "mcp_status" }>

export type SteerState = "accepted" | "delivered" | "discarded"

/** Why a turn of a chat's work period started (Cloud's `turn.why`). */
export type TurnWhy = "prompt" | "steer" | "wake" | "report"
/** How a background task ended (the `<compose_result>` status). */
export type TaskStatus = "completed" | "failed" | "cancelled"
/** How a turn or a work period ended. */
export type TurnHow = "finished" | "cancelled" | "error"

export interface ComposeStreamData {
  group: number
  slugs: string
  total_groups?: number
  status?: "starting" | "done" | "error"
  tool?: string
  toolUseId?: string
  toolResult?: string
  toolStatus?: ToolEndStatus
}

/**
 * The SSE `data:` shapes the chat UI reads. `work`, `turn`, `turnEnd` and `messageStart` are
 * Cloud's shapes (agent/session_runtime.py) for a chat's work period: it starts busy, holds one or
 * more turns (`text` is the user's message; "" for a hidden turn), and ends idle.
 */
export type SsePayload =
  | { event: { contentBlockDelta: { delta: { text: string } } } }
  | { event: { messageStart: { role: "assistant" } } }
  | { work: { state: "busy" } | { state: "idle"; how: TurnHow } }
  | { turn: { id: string; why: TurnWhy; text: string } }
  | { turnEnd: { id: string; how: TurnHow } }
  | { toolStart: { toolUseId: string; name: string } }
  | { toolUse: { toolUseId: string; name: string; input: Record<string, unknown> } }
  | { toolResult: { toolUseId: string; name: string; status: ToolEndStatus; content: string } }
  | { toolStream: { toolUseId: string; name: string; data: ComposeStreamData } }
  /** A background task started in place of its tool's result (Cloud's agent/streaming.py). */
  | { taskStart: { toolUseId: string; name: string; taskId: string } }
  /** It settled; `content` is its report (Cloud's agent/session_runtime.py). */
  | { taskEnd: { toolUseId: string; taskId: string; name: string; status: TaskStatus; content: string } }
  | { steer: { id: string; text?: string; state: SteerState } }
  | { notice: { code: LocalSessionNoticeCode } }
  | { status: "error"; code?: LocalTurnErrorCode; error: string }

export type ChatEvent =
  | { kind: "data"; payload: SsePayload }
  /** The work period is over: the stream writes the payload (an error) if any, then closes. */
  | { kind: "end"; stopReason?: string; payload?: SsePayload }

/** A ChatEvent with the number the chat gave it within its work period (the SSE `id:`). */
export interface BufferedEvent {
  id: number
  event: ChatEvent
}

export const data = (payload: SsePayload): ChatEvent => ({ kind: "data", payload })
