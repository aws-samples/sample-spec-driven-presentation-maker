// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A turn's end: stopReasons without a full answer end with their error code, every other
 * stopReason (end_turn, cancelled, one this client does not know) ends quietly; a failed
 * prompt ends with its message, a kiro-cli exit with agent_exited.
 */

import { describe, expect, it } from "vitest"

import { turnEnded, turnFailed } from "./turn"

describe("turnEnded", () => {
  it.each(["end_turn", "cancelled", "some_future_reason", "constructor"])("ends quietly on stopReason %s", (stopReason) => {
    expect(turnEnded(stopReason)).toEqual({ kind: "end", stopReason })
  })

  it.each(["refusal", "max_tokens", "max_turn_requests"])("ends with code %s", (stopReason) => {
    expect(turnEnded(stopReason)).toMatchObject({ kind: "end", stopReason, payload: { status: "error", code: stopReason, error: expect.any(String) } })
  })
})

describe("turnFailed", () => {
  it("ends with the prompt's error message", () => {
    expect(turnFailed({ message: "Internal error: prompt failed" })).toEqual({ kind: "end", payload: { status: "error", error: "Internal error: prompt failed" } })
  })

  it("ends with agent_exited and its chat text when kiro-cli exits", () => {
    expect(turnFailed({ code: "agent_exited", message: "kiro-cli exited with code null" }))
      .toMatchObject({ kind: "end", payload: { status: "error", code: "agent_exited", error: expect.stringMatching(/kiro-cli stopped/) } })
  })

  it("ends with a generic message when there is none", () => {
    expect(turnFailed({})).toEqual({ kind: "end", payload: { status: "error", error: "ACP request failed" } })
  })
})
