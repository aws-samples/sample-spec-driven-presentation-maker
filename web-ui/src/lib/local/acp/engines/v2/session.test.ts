// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V2 session: kiro-cli starts with `--agent <name>`, session/new carries no agent field and
 * must answer the agent's mode, then the sdpm server is waited for; opening a saved session is
 * session/new then session/load (prompts go to the loaded id), a `Session not found` keeps the
 * new session as `created`, another mode is switched with set_mode after the session's MCP
 * record was cleared; Stop cancels the main session and this turn's sub-agent sessions; the
 * models come from session/new; the lock and auth errors are recognised.
 */

import { describe, expect, it, vi } from "vitest"

import { AgentStartError } from "../../../turnErrors"
import type { SessionContext } from "../../engine"
import { AcpRequestError } from "../../transport"
import { v2Adapter } from "."
import { V2Session } from "./session"

const MODES = (current: string) => ({ currentModeId: current, availableModes: [{ id: "sdpm-orchestrator", name: "o" }, { id: "sdpm-style", name: "s" }] })

function context(answers: Record<string, unknown | ((params: Record<string, unknown>) => unknown)>) {
  const calls: { method: string; params?: Record<string, unknown> }[] = []
  const order: string[] = []
  const ctx: SessionContext = {
    request: vi.fn(async (method: string, params?: Record<string, unknown>, opts?: { onAnswer?: (a: { ok: boolean; result?: unknown }) => void }) => {
      calls.push({ method, params })
      order.push(method)
      const answer = answers[method]
      try {
        const result = typeof answer === "function" ? answer(params ?? {}) : (answer ?? {})
        opts?.onAnswer?.({ ok: true, result })
        return result
      } catch (error) {
        opts?.onAnswer?.({ ok: false })
        throw error
      }
    }),
    cwd: "/workspace/sdpm/servers/local",
    setupTimeoutMs: 1000,
    waitForMcp: vi.fn(async (sessionId: string) => { order.push(`wait ${sessionId}`) }),
    clearMcp: vi.fn((sessionId: string) => { order.push(`clear ${sessionId}`) }),
  }
  return { ctx, calls, order }
}

const NEW = { sessionId: "K1", modes: MODES("sdpm-orchestrator") }

describe("V2 adapter", () => {
  it("starts kiro-cli with --agent", () => {
    expect(v2Adapter.spawnArgs("sdpm-style")).toEqual(["acp", "--agent", "sdpm-style"])
  })
})

describe("V2Session", () => {
  it("creates a session without an agent field, waits for its sdpm server and offers its models", async () => {
    const { ctx, calls, order } = context({ "session/new": { ...NEW, models: { currentModelId: "auto", availableModels: [{ modelId: "auto", name: "auto" }] } } })
    const session = new V2Session(ctx)
    await expect(session.newSession("sdpm-orchestrator")).resolves.toEqual({ sessionId: "K1" })
    expect(calls).toEqual([{ method: "session/new", params: { cwd: "/workspace/sdpm/servers/local", mcpServers: [] } }])
    expect(order).toEqual(["session/new", "wait K1"])
    expect(session.models()).toEqual({ current: "auto", available: [{ modelId: "auto", name: "auto" }] })
    expect(session.cancelTargets()).toEqual(["K1"])
  })

  it("refuses a session in another mode (kiro_default for an agent V2 did not find)", async () => {
    vi.useFakeTimers()
    try {
      const { ctx } = context({ "session/new": { sessionId: "K1", modes: MODES("kiro_default") } })
      const pending = new V2Session(ctx).newSession("sdpm-orchestrator").catch((e: unknown) => e)
      await vi.advanceTimersByTimeAsync(2000)
      const error = await pending
      expect(error).toBeInstanceOf(AgentStartError)
      expect(error).toMatchObject({ code: "agent_definition_rejected", message: expect.stringContaining("kiro_default") })
      expect(ctx.waitForMcp).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("opens a saved session as session/new then session/load, and prompts go to the loaded id", async () => {
    const { ctx, calls, order } = context({ "session/new": NEW, "session/load": { modes: MODES("sdpm-orchestrator") } })
    const session = new V2Session(ctx)
    const onReplay = vi.fn()
    await expect(session.openSession("K9", "sdpm-orchestrator", { onReplay })).resolves.toEqual({ sessionId: "K9", outcome: "resumed" })
    expect(calls[1]).toEqual({ method: "session/load", params: { sessionId: "K9", cwd: "/workspace/sdpm/servers/local", mcpServers: [] } })
    expect(order).toEqual(["session/new", "session/load", "wait K9"])
    expect(onReplay).toHaveBeenLastCalledWith(0, true)
    expect(session.cancelTargets()).toEqual(["K9"])
  })

  it("keeps the new session when kiro-cli no longer has the saved one", async () => {
    const { ctx, order } = context({
      "session/new": NEW,
      "session/load": () => { throw new AcpRequestError({ code: -32603, message: "Internal error", data: "Failed to start session: Session not found: K9" }) },
    })
    const session = new V2Session(ctx)
    await expect(session.openSession("K9", "sdpm-orchestrator")).resolves.toEqual({ sessionId: "K1", outcome: "created" })
    expect(order).toEqual(["session/new", "session/load", "wait K1"])
    expect(session.cancelTargets()).toEqual(["K1"])
  })

  it("switches a loaded session in another mode to the agent's, after clearing its MCP record", async () => {
    const { ctx, calls, order } = context({ "session/new": NEW, "session/load": { modes: MODES("sdpm-style") } })
    const onSwitching = vi.fn()
    await new V2Session(ctx).openSession("K9", "sdpm-orchestrator", { onSwitching })
    expect(order).toEqual(["session/new", "session/load", "clear K9", "session/set_mode", "wait K9"])
    expect(calls[2].params).toEqual({ sessionId: "K9", modeId: "sdpm-orchestrator" })
    expect(onSwitching).toHaveBeenCalledOnce()
  })

  it("refuses a loaded session that does not offer the agent's mode", async () => {
    vi.useFakeTimers()
    try {
      const { ctx } = context({ "session/new": { sessionId: "K1", modes: MODES("sdpm-translate") }, "session/load": { modes: MODES("sdpm-style") } })
      const pending = new V2Session(ctx).openSession("K9", "sdpm-translate").catch((e: unknown) => e)
      await vi.advanceTimersByTimeAsync(2000)
      expect(await pending).toMatchObject({ code: "agent_definition_rejected" })
    } finally {
      vi.useRealTimers()
    }
  })

  it("cancels the main session and the sub-agent sessions kiro-cli lists as working", async () => {
    const { ctx } = context({ "session/new": NEW })
    const session = new V2Session(ctx)
    await session.newSession("sdpm-orchestrator")
    session.beginTurn()
    session.translate({ method: "_kiro.dev/subagent/list_update", params: { subagents: [
      { sessionId: "S1", status: { type: "terminated" } },
      { sessionId: "S2", status: { type: "working" } },
    ] } })
    expect(session.cancelTargets()).toEqual(["K1", "S2"])
  })

  it("recognises kiro-cli's lock error and ACP's auth required", () => {
    const session = new V2Session(context({}).ctx)
    expect(session.classifyError(new AcpRequestError({ message: "Internal error", data: "Failed to start session: Session is active in another process (PID 1)" }))).toBe("session_locked")
    expect(session.classifyError(new AcpRequestError({ code: -32000, message: "Authentication required" }))).toBe("auth_required")
    expect(session.classifyError(new Error("something else"))).toBeNull()
  })
})
