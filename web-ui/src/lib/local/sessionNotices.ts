// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Notices the Local invoke route attaches to a turn, shared by the route, the process manager and
 * the chat UI. The process manager buffers `{notice: {code}}` as the turn's first event; the chat
 * shows the `chat.*` message named here above the reply, in the user's language, and keeps it in `.chat.json`.
 *
 * - `context_not_carried_over`: the chat had a kiro session that kiro-cli no longer has (a deck's
 *   `.session`, a fork's copy, a released chat), so the turn runs in a new session, saved to
 *   `.session`, without the earlier conversation. A deck with no `.session` (made by an MCP
 *   client or Kiro CLI) also starts a new session, without this notice: it had no Web UI
 *   conversation to lose.
 * - `context_from_other_engine`: the deck's session also had turns on the other agent engine
 *   (the deck's `.session-engine`); each engine keeps its own copy of the history, so the agent
 *   does not have those turns. The deck files are up to date.
 */

export type LocalSessionNoticeCode = "context_not_carried_over" | "context_from_other_engine"

/** `chat` namespace keys (messages/en.json, ja.json). */
export const LOCAL_SESSION_NOTICE_KEYS: Record<LocalSessionNoticeCode, string> = {
  context_not_carried_over: "localContextNotCarriedOver",
  context_from_other_engine: "localContextFromOtherEngine",
}

export function isLocalSessionNoticeCode(code: unknown): code is LocalSessionNoticeCode {
  return typeof code === "string" && Object.hasOwn(LOCAL_SESSION_NOTICE_KEYS, code)
}
