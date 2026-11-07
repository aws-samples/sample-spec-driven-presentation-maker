// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Session conflicts on the Local invoke route (HTTP 409), shared by the route and the chat UI.
 *
 * - `session_busy`: this server's process for the session is still answering a prompt
 *   (the same chat open in two panels or tabs).
 * - `session_locked`: kiro-cli refused to load the session because another process holds its
 *   lock (for example `kiro-cli chat --resume` in a terminal). The engine adapter recognises
 *   kiro-cli's error (`EngineSession.classifyError`); the process manager throws SessionLockedError.
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

/** Thrown when kiro-cli refused to open a session another process holds; `message` is kiro-cli's. */
export class SessionLockedError extends Error {
  constructor(detail: string) {
    super(detail)
    this.name = "SessionLockedError"
  }
}

/** Thrown by a fork when kiro-cli made the fork but could not read it (its conversation would be empty). */
export class ForkNotReadError extends Error {
  constructor() {
    super("kiro-cli could not read the forked session")
    this.name = "ForkNotReadError"
  }
}

/** Map a spawn/load/prompt failure to a 409 body, or null when it is not a session conflict. */
export function sessionConflict(error: unknown): SessionConflict | null {
  if (error instanceof SessionBusyError) {
    return { code: "session_busy", error: "This chat is still answering a previous message. Wait for it to finish, then send again." }
  }
  if (error instanceof SessionLockedError) {
    return { code: "session_locked", error: `This chat session is in use by another kiro-cli process. Close it there, then send again. (${error.message})` }
  }
  return null
}

export function isSessionConflictCode(code: unknown): code is SessionConflictCode {
  return code === "session_busy" || code === "session_locked"
}
