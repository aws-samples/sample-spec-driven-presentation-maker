// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"

import type { McpStatusEvent } from "./conversation/events"
import { watchMcpServerReady, type McpStatusListener } from "./mcp-ready"

type Listener = McpStatusListener
const SID = "11111111-1111-4111-8111-111111111111"

function initialized(sessionId: string, server: string, state: McpStatusEvent["state"] = "connected"): McpStatusEvent {
  return { type: "mcp_status", sessionId, server, state }
}

function emit(listeners: Set<Listener>, event: McpStatusEvent) {
  for (const fn of [...listeners]) fn(event)
}

afterEach(() => { vi.useRealTimers() })

describe("watchMcpServerReady", () => {
  it("resolves when sdpm initializes after wait starts", async () => {
    const listeners = new Set<Listener>()
    const watch = watchMcpServerReady(listeners, SID)
    const ready = watch.wait(1000)
    emit(listeners, initialized(SID, "sdpm"))
    await expect(ready).resolves.toBe(true)
    expect(listeners.size).toBe(0)
  })

  it("remembers a notification that arrived before wait (ahead of the set_mode reply)", async () => {
    const listeners = new Set<Listener>()
    const watch = watchMcpServerReady(listeners, SID)
    emit(listeners, initialized(SID, "sdpm"))
    await expect(watch.wait(1000)).resolves.toBe(true)
  })

  it("ignores other servers, other sessions and states other than connected", async () => {
    vi.useFakeTimers()
    const listeners = new Set<Listener>()
    const watch = watchMcpServerReady(listeners, SID)
    const ready = watch.wait(1000)
    emit(listeners, initialized(SID, "builder-mcp"))
    emit(listeners, initialized("22222222-2222-4222-8222-222222222222", "sdpm"))
    emit(listeners, initialized(SID, "sdpm", "connecting"))
    await vi.advanceTimersByTimeAsync(1000)
    await expect(ready).resolves.toBe(false)
    expect(listeners.size).toBe(0)
  })

  it("rejects with AbortError when the fork is cancelled", async () => {
    const listeners = new Set<Listener>()
    const controller = new AbortController()
    const watch = watchMcpServerReady(listeners, SID)
    const ready = watch.wait(1000, controller.signal)
    controller.abort()
    await expect(ready).rejects.toMatchObject({ name: "AbortError" })
    expect(listeners.size).toBe(0)
  })

  it("dispose removes the listener without waiting", () => {
    const listeners = new Set<Listener>()
    watchMcpServerReady(listeners, SID).dispose()
    expect(listeners.size).toBe(0)
  })
})
