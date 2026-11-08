// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local steer: a message sent while the agent works goes into the running turn with ACP
 * `_session/steer {sessionId, message}`. The chat (chat.ts) sends it; this module holds the
 * steers kiro-cli queued and the chat events that report them.
 *
 * A steer's life is reported as `{steer: {id, text?, state}}`, the shape of the Cloud session's
 * steer event, buffered with the turn's other events:
 * - `accepted`: kiro-cli queued it; the chat shows the message where it was accepted.
 * - `delivered`: kiro-cli put it into the turn (the engine adapter's `steer_injected`), or the
 *   prompt ended (end_turn) before kiro-cli read it and it went into a follow-up prompt on the
 *   same turn, as Cloud does.
 * - `discarded`: a Stop, a kiro-cli exit or a failed turn ended the turn before kiro-cli read it.
 * Either way it is cleared from kiro-cli's queue (`_session/steer/clear`) first: left there,
 * kiro-cli would put it into the user's next message.
 *
 * A steer kiro-cli does not accept (no turn running, `queued: false`, an error) is refused with
 * SteerRejectedError; the route answers 409 with its code.
 */
import { data, type ChatEvent, type SteerState } from "./events"

export type { SteerState }

export type SteerRejectedCode = "session_idle" | "steer_not_queued"

export class SteerRejectedError extends Error {
  constructor(readonly code: SteerRejectedCode, detail?: string) {
    super(code === "session_idle"
      ? "No turn is running in this chat; send the message as a new one."
      : `kiro-cli did not queue the message${detail ? ` (${detail})` : ""}.`)
    this.name = "SteerRejectedError"
  }
}

export interface Steer {
  /** The chat's id for the message. */
  id: string
  text: string
  /** kiro-cli's id for it, when its answer to `_session/steer` carries one. */
  messageId?: string
  /** A text of the Local server for the agent (a harness steer): never reported in the chat. */
  hidden?: true
}

/** The steers kiro-cli queued in the running turn and has not reported read. */
export class SteerQueue {
  private steers: Steer[] = []

  get size(): number {
    return this.steers.length
  }

  add(steer: Steer): void {
    this.steers.push(steer)
  }

  /** Take out the steer kiro-cli reports it read: by its messageId, else by its text. */
  match(injected: { messageId?: string; content?: string }): Steer | null {
    let at = injected.messageId ? this.steers.findIndex((s) => s.messageId === injected.messageId) : -1
    if (at < 0 && injected.content !== undefined) {
      const content = injected.content.trim()
      at = this.steers.findIndex((s) => s.text.trim() === content)
    }
    if (at < 0) return null
    return this.steers.splice(at, 1)[0]
  }

  /** The queued steers, oldest first, left in the queue. */
  peek(): Steer[] {
    return [...this.steers]
  }

  /** Remove these steers (taken by `peek`) and keep the ones queued since. */
  remove(taken: readonly Steer[]): void {
    this.steers = this.steers.filter((steer) => !taken.includes(steer))
  }

  takeAll(): Steer[] {
    const all = this.steers
    this.steers = []
    return all
  }
}

export function steerEvent(steer: { id: string; text?: string; state: SteerState }): ChatEvent {
  return data({ steer: { id: steer.id, ...(steer.text !== undefined ? { text: steer.text } : {}), state: steer.state } })
}
