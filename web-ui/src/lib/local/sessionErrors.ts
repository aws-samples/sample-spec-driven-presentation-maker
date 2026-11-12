// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Session conflicts on the Local invoke route (HTTP 409), shared by the route and the chat UI.
 *
 * - `session_busy`: this server's chat for the session is still answering a prompt, or its
 *   stopped work is settling (the same chat open in two panels or tabs).
 * - `session_locked`: kiro-cli refused to load the session because a kiro-cli outside this server
 *   holds its lock (for example `kiro-cli chat --resume` in a terminal); this server opens a kiro
 *   session in one chat at most, so it never locks itself out. The engine adapter recognises
 *   kiro-cli's error (`EngineSession.classifyError`, only V2's does), the host reports it as
 *   HostOpenError `session_locked`, and the registry throws SessionLockedError.
 *
 * When the V2 engine is removed (its folder `acp/engines/v2/`), this goes with it, unless V3's
 * adapter reports a lock of its own by then: SessionLockedError and the `session_locked` member of
 * SessionConflictCode / `sessionConflict` here; the `"session_locked"` member of EngineErrorKind
 * (acp/engine.ts); HostOpenError and its mapping (hosts.ts, acp-process.ts `openChat`); the
 * `session_locked` case in `app/api/agent/invoke/route.test.ts` and in `chat.test.ts` ("session
 * held by another process"); the `sessionLocked` branch in `hooks/useChatStream.ts` and its
 * `session_locked` row in `hooks/useChatStream.test.tsx`; the `sessionLocked` keys in
 * `messages/en.json` / `ja.json`.
 */

export type SessionConflictCode = "session_busy" | "session_locked"

export interface SessionConflict {
  code: SessionConflictCode
  error: string
}

/** Thrown by sendPrompt while the chat's turn runs or its stopped work settles. */
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

/**
 * A chat's model choice that was not taken (PUT /api/agent/models):
 * - `unknown_model`: not one of the models the chat is offered.
 * - `effort_not_supported`: an effort for a model without effort levels (every V2 model).
 * - `unknown_effort`: not one of the model's effort levels.
 * - `models_unknown`: no model list is known yet (no kiro-cli has reported one).
 * - `model_not_changed`: kiro-cli refused the change; `message` is its error.
 */
export type ModelChoiceErrorCode = "unknown_model" | "effort_not_supported" | "unknown_effort" | "models_unknown" | "model_not_changed"

export class ModelChoiceError extends Error {
  constructor(readonly code: ModelChoiceErrorCode, detail?: string) {
    super(detail ?? code)
    this.name = "ModelChoiceError"
  }
}
