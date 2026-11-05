// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect } from "vitest"
import { classifyAgentError, agentErrorMessage } from "./agentErrors"

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

describe("agentErrorMessage with session_reload_required", () => {
  it("maps the code to the English reload message", () => {
    expect(agentErrorMessage("Reload the page", "session_reload_required")).toBe(
      "This page is out of date. Reload the page, then send again.",
    )
  })

  it("uses the translator when it returns a string", () => {
    const translate = (code: string) => (code === "session_reload_required" ? "translated" : undefined)
    expect(agentErrorMessage("Reload the page", "session_reload_required", translate)).toBe("translated")
  })

  it("falls back to English when the translator returns undefined", () => {
    expect(agentErrorMessage("raw", "throttled", () => undefined)).toMatch(/temporarily busy/)
  })

  it("asks the translator for a code outside its table before classifying", () => {
    const translate = (code: string) => (code === "agent_exited" ? "translated" : undefined)
    expect(agentErrorMessage("kiro-cli stopped", "agent_exited", translate)).toBe("translated")
    expect(agentErrorMessage("timed out waiting", "future_code", translate)).toMatch(/took too long/)
  })
})
