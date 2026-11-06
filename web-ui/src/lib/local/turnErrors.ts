// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * How a Local turn ends, shared by the ACP process manager, the conversation model and the chat UI.
 *
 * The process manager ends the turn it started when session/prompt is answered with a result (its
 * stopReason) or with an error, or when the kiro-cli process ends first (lib/local/conversation/
 * turn.ts). The stream's last event is then `{status: "error", code, error}` with one of the
 * codes below (the invoke route answers `agent_timeout` with 504 before a stream exists); the
 * chat UI shows the `chat.*` message named here, in the user's language. `error` carries the
 * English text for logs.
 *
 * - `agent_exited`: the kiro-cli process ended while the turn ran.
 * - `agent_timeout`: kiro-cli did not answer initialize / session/new / session/load in time.
 * - `refusal`, `max_tokens`, `max_turn_requests`: the turn's ACP stopReason.
 */

export type LocalTurnErrorCode = "agent_exited" | "agent_timeout" | "refusal" | "max_tokens" | "max_turn_requests"

const ENGLISH: Record<LocalTurnErrorCode, string> = {
  agent_exited: "kiro-cli stopped while it was answering. Send your message again.",
  agent_timeout: "kiro-cli did not respond in time. Send again; if this keeps happening, run kiro-cli in a terminal to check it.",
  refusal: "The model declined to answer this request. Rephrase it and send again.",
  max_tokens: "The response hit the model's output limit. Ask for a smaller step and send again.",
  max_turn_requests: "The agent reached its step limit for one turn. Send a message to let it continue.",
}

/** `chat` namespace keys (messages/en.json, ja.json). */
export const LOCAL_TURN_ERROR_KEYS: Record<LocalTurnErrorCode, string> = {
  agent_exited: "localAgentExited",
  agent_timeout: "localAgentTimeout",
  refusal: "localRefusal",
  max_tokens: "localMaxTokens",
  max_turn_requests: "localMaxTurnRequests",
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
