// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Notices the Local invoke route attaches to a turn, shared by the route, the process manager and
 * the chat UI. The process manager buffers `{notice: {code}}` as the turn's first event; the chat
 * shows the `chat.*` message named here above the reply, in the user's language, and keeps it in `.chat.json`.
 *
 * - `context_not_carried_over`: the deck had no kiro session to load — no `.session` (a deck made
 *   by an MCP client or Kiro CLI) or one kiro-cli no longer has — so the turn runs in a new
 *   session, saved to `.session`, without the earlier conversation.
 */

export type LocalSessionNoticeCode = "context_not_carried_over"

/** `chat` namespace keys (messages/en.json, ja.json). */
export const LOCAL_SESSION_NOTICE_KEYS: Record<LocalSessionNoticeCode, string> = {
  context_not_carried_over: "localContextNotCarriedOver",
}

export function isLocalSessionNoticeCode(code: unknown): code is LocalSessionNoticeCode {
  return typeof code === "string" && Object.hasOwn(LOCAL_SESSION_NOTICE_KEYS, code)
}
