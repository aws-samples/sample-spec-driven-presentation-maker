// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Session conflicts on the Local invoke route (HTTP 409), shared by the route and the chat UI.
 *
 * - `session_busy`: this server's process for the session is still answering a prompt
 *   (the same chat open in two panels or tabs).
 * - `session_locked`: kiro-cli refused to load the session because another process holds its
 *   lock (for example `kiro-cli chat --resume` in a terminal).
 */

export type SessionConflictCode = "session_busy" | "session_locked"

export interface SessionConflict {
  code: SessionConflictCode
  error: string
}

/** Thrown by sendPrompt when the session's previous prompt has not finished. */
export class SessionBusyError extends Error {
  constructor() {
    super("This chat is still answering a previous message.")
    this.name = "SessionBusyError"
  }
}

/** kiro-cli's session/load error while another live process holds the session lock. */
const SESSION_LOCKED_MARKER = "Session is active in another process"

/** Map a spawn/load/prompt failure to a 409 body, or null when it is not a session conflict. */
export function sessionConflict(error: unknown): SessionConflict | null {
  if (error instanceof SessionBusyError) {
    return { code: "session_busy", error: "This chat is still answering a previous message. Wait for it to finish, then send again." }
  }
  if (error instanceof Error && error.message.includes(SESSION_LOCKED_MARKER)) {
    return { code: "session_locked", error: `This chat session is in use by another kiro-cli process. Close it there, then send again. (${error.message})` }
  }
  return null
}

export function isSessionConflictCode(code: unknown): code is SessionConflictCode {
  return code === "session_busy" || code === "session_locked"
}
