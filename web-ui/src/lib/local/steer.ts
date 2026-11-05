// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local steer: a message sent while the agent works goes into the running turn with ACP
 * `_session/steer {sessionId, message}` (kiro-cli V2 and V3). Shared by the process manager,
 * the SSE bridge and the steer route.
 *
 * The process manager reports a steer's life with an event of its own, `STEER_EVENT`
 * `{id, text?, state}`, buffered and forwarded like the turn events (turnErrors.ts); the bridge
 * sends it as `{steer: {id, text?, state}}`, the shape of the Cloud session's steer event:
 * - `accepted`: kiro-cli queued it; the chat shows the message where it was accepted.
 * - `delivered`: kiro-cli put it into the turn (V2 `AgentExecutionSteeringInjected`,
 *   V3 `session_info_update` kind `steering_injected`), or the prompt ended (end_turn) before
 *   kiro-cli read it and it went into a follow-up prompt on the same turn, as Cloud does.
 * - `discarded`: a Stop, a kiro-cli exit or a failed turn ended the turn before kiro-cli read it.
 * Either way it is cleared from kiro-cli's queue (`_session/steer/clear`) first: left there,
 * kiro-cli V2 and V3 would put it into the user's next message.
 *
 * A steer kiro-cli does not accept (no turn running, `queued: false`, an error) is refused with
 * SteerRejectedError; the route answers 409 with its code.
 */

export const STEER_EVENT = "_sdpm/steer"

export type SteerState = "accepted" | "delivered" | "discarded"

export type SteerRejectedCode = "session_idle" | "steer_not_queued"

export class SteerRejectedError extends Error {
  constructor(readonly code: SteerRejectedCode, detail?: string) {
    super(code === "session_idle"
      ? "No turn is running in this chat; send the message as a new one."
      : `kiro-cli did not queue the message${detail ? ` (${detail})` : ""}.`)
    this.name = "SteerRejectedError"
  }
}

/** A steer kiro-cli reports it read, by its messageId (V3, V2) and its text (V2 answers no id). */
export interface SteerInjection {
  messageId?: string
  content?: string
}

/**
 * The injection a kiro-cli notification reports, or null. V2 sends `_kiro.dev/session/update`
 * `AgentExecutionSteeringInjected {messageId, content}`; V3 sends `session/update`
 * `session_info_update` with `_meta.kiro {kind: "steering_injected", messageId, content}`.
 */
export function steerInjection(msg: Record<string, unknown>): SteerInjection | null {
  const update = (msg.params as { update?: Record<string, unknown> } | undefined)?.update
  if (!update) return null
  if (msg.method === "_kiro.dev/session/update" && update.sessionUpdate === "AgentExecutionSteeringInjected") {
    return { messageId: update.messageId as string | undefined, content: update.content as string | undefined }
  }
  if (msg.method === "session/update" && update.sessionUpdate === "session_info_update") {
    const kiro = (update._meta as { kiro?: Record<string, unknown> } | undefined)?.kiro
    if (kiro?.kind === "steering_injected") {
      return { messageId: kiro.messageId as string | undefined, content: kiro.content as string | undefined }
    }
  }
  return null
}
