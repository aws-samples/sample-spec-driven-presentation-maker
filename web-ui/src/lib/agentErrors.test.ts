// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect } from "vitest"
import { classifyAgentError, agentErrorMessage, isRetryableAgentError } from "./agentErrors"

describe("classifyAgentError", () => {
  it.each([
    ["Too much media in the conversation", "conversation_too_long"],
    ["ThrottlingException: rate exceeded", "throttled"],
    ["ModelTimeoutException after 60s", "timeout"],
    ["ModelNotReadyException", "model_not_ready"],
    ["ServiceUnavailable: try later", "service_unavailable"],
    ["ExpiredToken: credentials expired", "auth"],
    ["ValidationException: bad schema", "bad_input"],
    ["something totally unexpected", "internal"],
  ])("classifies %s → %s", (msg, expected) => {
    expect(classifyAgentError(msg)).toBe(expected)
  })
})

describe("agentErrorMessage", () => {
  it("prefers the code from the event over pattern matching", () => {
    expect(agentErrorMessage("raw text", "throttled")).toMatch(/temporarily busy/)
  })

  it("falls back to pattern matching when no code", () => {
    expect(agentErrorMessage("ThrottlingException: rate exceeded")).toMatch(/temporarily busy/)
  })

  it("keeps the raw message for unclassified errors without a code", () => {
    expect(agentErrorMessage("Custom failure detail")).toBe("Custom failure detail")
  })

  it("uses the generic message for internal errors with an explicit code", () => {
    expect(agentErrorMessage("stack trace...", "internal")).toMatch(/something went wrong/)
  })

  it("ignores unknown codes and falls back to classification", () => {
    expect(agentErrorMessage("timed out waiting", "future_code")).toMatch(/took too long/)
  })
})

describe("isRetryableAgentError", () => {
  it("marks throttling and timeouts retryable", () => {
    expect(isRetryableAgentError("", "throttled")).toBe(true)
    expect(isRetryableAgentError("timed out")).toBe(true)
  })

  it("marks auth and conversation-limit not retryable", () => {
    expect(isRetryableAgentError("", "auth")).toBe(false)
    expect(isRetryableAgentError("Too much media")).toBe(false)
  })
})
