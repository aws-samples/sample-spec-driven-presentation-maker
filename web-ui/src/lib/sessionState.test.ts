// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { RESUME_WINDOW_MS, createSessionStateWriter, isResumable, readSessionState } from "./sessionState"

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
})
afterEach(() => vi.useRealTimers())

describe("sessionState", () => {
  it("writes a state change at once and seq updates at most once a second", () => {
    const writer = createSessionStateWriter("s1")
    writer.update("working", 1)
    expect(readSessionState("s1")).toMatchObject({ state: "working", lastSeq: 1 })
    writer.update("working", 2)
    writer.update("working", 3)
    expect(readSessionState("s1")?.lastSeq).toBe(1)
    vi.advanceTimersByTime(1000)
    expect(readSessionState("s1")?.lastSeq).toBe(3)
    writer.update("working", 4)
    writer.update("idle", 5)
    expect(readSessionState("s1")).toMatchObject({ state: "idle", lastSeq: 5 })
  })

  it("is resumable only while the last state is working and recent", () => {
    expect(isResumable("none")).toBe(false)
    createSessionStateWriter("w").update("working", 1)
    expect(isResumable("w")).toBe(true)
    expect(isResumable("w", Date.now() + RESUME_WINDOW_MS)).toBe(false)
    createSessionStateWriter("i").update("idle", 1)
    expect(isResumable("i")).toBe(false)
  })

  it("ignores a malformed entry", () => {
    localStorage.setItem("sdpm-session:x", "{not json")
    expect(readSessionState("x")).toBeNull()
  })
})
