// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The MCP record and the wait on it: a state recorded before the wait ends it at once
 * (connected → true, failed → McpFailedError); a later update ends it; other servers, other
 * sessions and `connecting` do not; a snapshot and `clear` empty a session's record; the wait
 * times out with false and follows the abort signal.
 */

import { afterEach, describe, expect, it, vi } from "vitest"

import type { McpStatusEvent } from "./conversation/events"
import { McpFailedError, McpRecord, waitForMcp } from "./mcp-ready"

const SID = "11111111-1111-4111-8111-111111111111"
const OTHER = "22222222-2222-4222-8222-222222222222"

const status = (sessionId: string, server: string, state: McpStatusEvent["state"], error?: string): McpStatusEvent =>
  ({ type: "mcp_status", sessionId, server, state, ...(error ? { error } : {}) })

afterEach(() => { vi.useRealTimers() })

describe("waitForMcp", () => {
  it("ends at once when sdpm was recorded connected before the wait (V2 reports it ahead of its answer)", async () => {
    const record = new McpRecord()
    record.apply(status(SID, "sdpm", "connected"))
    await expect(waitForMcp(record, SID)).resolves.toBe(true)
  })

  it("fails at once with McpFailedError when sdpm was recorded failed", async () => {
    const record = new McpRecord()
    record.apply(status(SID, "sdpm", "failed", "connection closed"))
    const error = await waitForMcp(record, SID).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(McpFailedError)
    expect(error).toMatchObject({ code: "mcp_failed", message: expect.stringContaining("connection closed") })
  })

  it("waits through connecting until a later update says connected", async () => {
    const record = new McpRecord()
    record.apply(status(SID, "sdpm", "connecting"))
    const ready = waitForMcp(record, SID, "sdpm", 1000)
    record.apply(status(SID, "sdpm", "connected"))
    await expect(ready).resolves.toBe(true)
  })

  it("ignores other servers, other sessions and connecting, then times out with false", async () => {
    vi.useFakeTimers()
    const record = new McpRecord()
    const ready = waitForMcp(record, SID, "sdpm", 1000)
    record.apply(status(SID, "builder-mcp", "connected"))
    record.apply(status(OTHER, "sdpm", "connected"))
    record.apply(status(SID, "sdpm", "connecting"))
    await vi.advanceTimersByTimeAsync(1000)
    await expect(ready).resolves.toBe(false)
  })

  it("does not count a state from before a snapshot or a clear", async () => {
    vi.useFakeTimers()
    const record = new McpRecord()
    record.apply(status(SID, "sdpm", "connected"))
    record.apply({ type: "mcp_snapshot", sessionId: SID })
    const afterSnapshot = waitForMcp(record, SID, "sdpm", 1000)
    await vi.advanceTimersByTimeAsync(1000)
    await expect(afterSnapshot).resolves.toBe(false)

    record.apply(status(SID, "sdpm", "connected"))
    record.clear(SID)
    const afterClear = waitForMcp(record, SID, "sdpm", 1000)
    record.apply(status(SID, "sdpm", "connected"))
    await expect(afterClear).resolves.toBe(true)
  })

  it("rejects with AbortError when the caller aborts", async () => {
    const record = new McpRecord()
    const controller = new AbortController()
    const ready = waitForMcp(record, SID, "sdpm", 1000, controller.signal)
    controller.abort()
    await expect(ready).rejects.toMatchObject({ name: "AbortError" })
  })
})
