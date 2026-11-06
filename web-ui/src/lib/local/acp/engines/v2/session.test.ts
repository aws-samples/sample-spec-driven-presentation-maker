// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V2 session: session/new carries no agent field (`--agent` picks the agent); opening a saved
 * session is session/new then session/load, prompts then go to the loaded id; a fork also checks
 * the agent's mode, switches to it and waits for its sdpm server; Stop cancels the main session
 * and this turn's sub-agent sessions; the models come from session/new.
 */

import { describe, expect, it, vi } from "vitest"

import type { SessionContext } from "../../engine"
import type { McpReadyWatch } from "../../../mcp-ready"
import { V2Session } from "./session"

function context(answers: Record<string, unknown>, ready = true) {
  const calls: { method: string; params?: Record<string, unknown> }[] = []
  const watch: McpReadyWatch = { wait: vi.fn(async () => ready), dispose: vi.fn() }
  const ctx: SessionContext = {
    request: vi.fn(async (method: string, params?: Record<string, unknown>, opts?: { onAnswer?: (a: { ok: true; result: unknown }) => void }) => {
      calls.push({ method, params })
      const result = answers[method] ?? {}
      opts?.onAnswer?.({ ok: true, result })
      return result
    }),
    cwd: "/workspace/sdpm/servers/local",
    setupTimeoutMs: 1000,
    mcpReadyTimeoutMs: 500,
    watchMcp: vi.fn(() => watch),
  }
  return { ctx, calls, watch }
}

const MODES = { modes: { currentModeId: "sdpm-orchestrator", availableModes: [{ id: "sdpm-orchestrator", name: "o" }] } }

describe("V2Session", () => {
  it("creates a session without an agent field and offers its models", async () => {
    const { ctx, calls } = context({ "session/new": { sessionId: "K1", models: { currentModelId: "auto", availableModels: [{ modelId: "auto", name: "auto" }] } } })
    const session = new V2Session(ctx)
    await expect(session.newSession()).resolves.toEqual({ sessionId: "K1" })
    expect(calls).toEqual([{ method: "session/new", params: { cwd: "/workspace/sdpm/servers/local", mcpServers: [] } }])
    expect(session.models()).toEqual({ current: "auto", available: [{ modelId: "auto", name: "auto" }] })
    expect(session.cancelTargets()).toEqual(["K1"])
  })

  it("opens a saved session as session/new then session/load, and prompts go to the loaded id", async () => {
    const { ctx, calls } = context({ "session/new": { sessionId: "K1" } })
    const session = new V2Session(ctx)
    await expect(session.openSession("K9", "sdpm-orchestrator")).resolves.toEqual({ sessionId: "K9", outcome: "resumed" })
    expect(calls.map((c) => c.method)).toEqual(["session/new", "session/load"])
    expect(calls[1].params).toEqual({ sessionId: "K9", cwd: "/workspace/sdpm/servers/local", mcpServers: [] })
    expect(ctx.watchMcp).not.toHaveBeenCalled()
    expect(session.cancelTargets()).toEqual(["K9"])
  })

  it("switches a fork to the agent's mode and waits for its sdpm server", async () => {
    const { ctx, calls, watch } = context({ "session/new": { sessionId: "K1" }, "session/load": MODES })
    const onSwitching = vi.fn()
    const session = new V2Session(ctx)
    await session.openSession("K9", "sdpm-orchestrator", { setMode: true, onSwitching })
    expect(calls.map((c) => c.method)).toEqual(["session/new", "session/load", "session/set_mode"])
    expect(calls[2].params).toEqual({ sessionId: "K9", modeId: "sdpm-orchestrator" })
    expect(ctx.watchMcp).toHaveBeenCalledWith("K9")
    expect(onSwitching).toHaveBeenCalledOnce()
    expect(watch.wait).toHaveBeenCalledWith(500, undefined)
  })

  it("refuses a fork whose session does not offer the agent's mode", async () => {
    const { ctx, watch } = context({ "session/new": { sessionId: "K1" }, "session/load": MODES })
    await expect(new V2Session(ctx).openSession("K9", "sdpm-style", { setMode: true })).rejects.toThrow(/mode sdpm-style unavailable/)
    expect(watch.dispose).toHaveBeenCalled()
  })

  it("cancels the main session and the sub-agent sessions this turn ran", async () => {
    const { ctx } = context({ "session/new": { sessionId: "K1" } })
    const session = new V2Session(ctx)
    await session.newSession()
    session.beginTurn()
    session.translate({ method: "session/update", params: { sessionId: "S2", update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "x" } } } })
    expect(session.cancelTargets()).toEqual(["K1", "S2"])
  })
})
