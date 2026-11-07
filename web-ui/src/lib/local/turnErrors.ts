// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * How a Local turn ends, shared by the ACP process manager, the conversation model and the chat UI.
 *
 * The process manager ends the turn it started when session/prompt is answered with a result (its
 * stopReason) or with an error, or when the kiro-cli process ends first (lib/local/conversation/
 * turn.ts). The stream's last event is then `{status: "error", code, error}` with one of the
 * codes below; a turn that cannot start is answered by the invoke route before a stream exists
 * (504 `agent_timeout`, 502 for the start-up codes). The chat UI shows the `chat.*` message named
 * here, in the user's language. `error` carries the English text for logs.
 *
 * - `agent_exited`: the kiro-cli process ended while the turn ran.
 * - `agent_timeout`: kiro-cli did not answer initialize / session/new / session/load in time.
 * - `refusal`, `max_tokens`, `max_turn_requests`: the turn's ACP stopReason.
 * - Start-up failures (AgentStartError):
 *   - `agent_start_failed`: kiro-cli could not be started or exited while starting (not
 *     installed, too old for the engine's arguments), or the agent definitions could not be
 *     generated.
 *   - `agent_auth_required`: kiro-cli is not signed in.
 *   - `agent_definition_rejected`: kiro-cli started another agent than the sdpm one asked for.
 *   - `mcp_failed`: the sdpm MCP server reported that it failed to start.
 */

export type AgentStartErrorCode = "agent_start_failed" | "agent_auth_required" | "agent_definition_rejected" | "mcp_failed"

export type LocalTurnErrorCode = "agent_exited" | "agent_timeout" | "refusal" | "max_tokens" | "max_turn_requests" | AgentStartErrorCode

const ENGLISH: Record<LocalTurnErrorCode, string> = {
  agent_exited: "kiro-cli stopped while it was answering. Send your message again.",
  agent_timeout: "kiro-cli did not respond in time. Send again; if this keeps happening, run kiro-cli in a terminal to check it.",
  refusal: "The model declined to answer this request. Rephrase it and send again.",
  max_tokens: "The response hit the model's output limit. Ask for a smaller step and send again.",
  max_turn_requests: "The agent reached its step limit for one turn. Send a message to let it continue.",
  agent_start_failed: "kiro-cli could not start. Check that kiro-cli 3.0 or later is installed, or switch the agent engine to V2 in Settings.",
  agent_auth_required: "kiro-cli is not signed in. Run `kiro-cli login` in a terminal, then send again.",
  agent_definition_rejected: "kiro-cli did not accept the sdpm agent definitions. Update kiro-cli, or switch the agent engine to V2 in Settings.",
  mcp_failed: "The sdpm MCP server did not start. Check that uv is installed, then send again.",
}

/** `chat` namespace keys (messages/en.json, ja.json). */
export const LOCAL_TURN_ERROR_KEYS: Record<LocalTurnErrorCode, string> = {
  agent_exited: "localAgentExited",
  agent_timeout: "localAgentTimeout",
  refusal: "localRefusal",
  max_tokens: "localMaxTokens",
  max_turn_requests: "localMaxTurnRequests",
  agent_start_failed: "localAgentStartFailed",
  agent_auth_required: "localAgentAuthRequired",
  agent_definition_rejected: "localAgentDefinitionRejected",
  mcp_failed: "localMcpFailed",
}

export function isLocalTurnErrorCode(code: unknown): code is LocalTurnErrorCode {
  return typeof code === "string" && Object.hasOwn(ENGLISH, code)
}

/** The bridge's error event for a turn that ended without an answer. */
export function localTurnError(code: LocalTurnErrorCode): { status: "error"; code: LocalTurnErrorCode; error: string } {
  return { status: "error", code, error: ENGLISH[code] }
}

/** Thrown when kiro-cli does not answer a setup request (initialize, session/new, session/load) in time. */
export class AgentTimeoutError extends Error {
  readonly code = "agent_timeout" as const
  constructor(method: string, timeoutMs: number) {
    super(`kiro-cli did not answer ${method} within ${Math.round(timeoutMs / 1000)}s`)
    this.name = "AgentTimeoutError"
  }
}

/** kiro-cli could not be made ready for a chat; the process was killed and not registered. `message` is for logs. */
export class AgentStartError extends Error {
  constructor(readonly code: AgentStartErrorCode, detail: string) {
    super(detail)
    this.name = "AgentStartError"
  }
}
