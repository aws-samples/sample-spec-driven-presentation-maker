// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The end of a turn as a chat event. The process manager ends a turn only when its own
 * session/prompt is answered (with a result or an error) or kiro-cli exits first; the stream then
 * writes the end event's payload, if any, and closes.
 */
import { isLocalTurnErrorCode, localTurnError, type LocalTurnErrorCode } from "../turnErrors"
import type { ChatEvent } from "./events"

/**
 * ACP stopReasons that end a turn without a full answer. end_turn and cancelled (Stop) close the
 * stream quietly, and so does a stopReason this table does not know: every answer closes it.
 */
const STOP_REASON_ERRORS: Record<string, LocalTurnErrorCode> = {
  refusal: "refusal",
  max_tokens: "max_tokens",
  max_turn_requests: "max_turn_requests",
}

/** session/prompt was answered with a result. */
export function turnEnded(stopReason: string): ChatEvent {
  const code = Object.hasOwn(STOP_REASON_ERRORS, stopReason) ? STOP_REASON_ERRORS[stopReason] : undefined
  return { kind: "end", stopReason, ...(code ? { payload: localTurnError(code) } : {}) }
}

/** session/prompt was answered with an error, or kiro-cli exited first (`code: "agent_exited"`). */
export function turnFailed(failure: { code?: string; message?: string }): ChatEvent {
  return {
    kind: "end",
    payload: isLocalTurnErrorCode(failure.code)
      ? localTurnError(failure.code)
      : { status: "error", error: failure.message || "ACP request failed" },
  }
}
