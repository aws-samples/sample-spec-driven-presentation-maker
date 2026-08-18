// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Agent stream error classification — mirrors agent/errors.py.
 *
 * Prefers the stable `code` field on error events; falls back to message
 * pattern matching for older agent deployments that don't send codes.
 */

export type AgentErrorCode =
  | "conversation_too_long"
  | "throttled"
  | "timeout"
  | "model_not_ready"
  | "service_unavailable"
  | "auth"
  | "bad_input"
  | "max_output"
  | "internal"

const MESSAGES: Record<AgentErrorCode, string> = {
  conversation_too_long: "This conversation is too long for the model to process. Please start a new chat to continue.",
  throttled: "The service is temporarily busy. Please wait a moment and try again.",
  timeout: "The model took too long to respond. Please try again.",
  model_not_ready: "The model is not ready yet. Please wait a moment and try again.",
  service_unavailable: "The service is temporarily unavailable. Please try again later.",
  auth: "Your session has expired or is not authorized. Please sign in again.",
  bad_input: "The request could not be processed. Please adjust your input and try again.",
  max_output: "The response hit the model's output limit. Ask for a smaller step and try again.",
  internal: "Sorry, something went wrong. Please try again.",
}

const PATTERNS: [string[], AgentErrorCode][] = [
  [["Too much media", "too long"], "conversation_too_long"],
  [["ThrottlingException", "throttl"], "throttled"],
  [["ModelTimeoutException", "timed out", "timeout"], "timeout"],
  [["ModelNotReadyException", "not ready"], "model_not_ready"],
  [["ServiceUnavailable"], "service_unavailable"],
  [["ExpiredToken", "AccessDenied", "UnrecognizedClient", "invalid_token"], "auth"],
  [["ValidationException"], "bad_input"],
  [["MaxTokensReachedException", "maximum token limit"], "max_output"],
]

/** Classify a raw error message into a stable code (fallback path). */
export function classifyAgentError(message: string): AgentErrorCode {
  for (const [needles, code] of PATTERNS) {
    if (needles.some((n) => message.includes(n))) return code
  }
  return "internal"
}

/**
 * User-facing message for an agent error event.
 *
 * @param message - Raw error text from the event
 * @param code - Stable code from the event, when present
 */
export function agentErrorMessage(message: string, code?: string): string {
  const resolved = (code && code in MESSAGES ? code : classifyAgentError(message)) as AgentErrorCode
  // Unclassified internal errors keep the raw message — it's more actionable
  // than a generic apology when nothing matched.
  if (resolved === "internal" && !code && message) return message
  return MESSAGES[resolved]
}

/** Whether the user can fix this by simply retrying. */
export function isRetryableAgentError(message: string, code?: string): boolean {
  const resolved = (code && code in MESSAGES ? code : classifyAgentError(message)) as AgentErrorCode
  return resolved === "throttled" || resolved === "timeout" || resolved === "model_not_ready" || resolved === "service_unavailable"
}
