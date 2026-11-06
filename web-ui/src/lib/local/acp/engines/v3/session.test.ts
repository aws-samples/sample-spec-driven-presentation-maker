// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V3 session: kiro-cli starts with `--agent-engine v3`; session/new asks for the agent's mode
 * in `_meta.kiro.modeId` and must answer it (`vibe` is a rejected definition), then the sdpm
 * server is waited for; a saved session is opened with session/load alone, `created` when its
 * `_meta.createdAt` is not older than the load (less a second), `resumed` otherwise or without
 * one; another mode is switched with set_mode after the session's MCP record was cleared; Stop
 * cancels the main session only; the capabilities come from initialize; auth required is
 * recognised.
 */

import { afterEach, describe, expect, it, vi } from "vitest"

import type { SessionContext } from "../../engine"
import { AcpRequestError } from "../../transport"
import { v3Adapter } from "."
import { V3Session } from "./session"

const MODES = (current: string) => ({ currentModeId: current, availableModes: [{ id: "sdpm-orchestrator", name: "o" }, { id: "sdpm-style", name: "s" }] })
const LOAD_AT = Date.parse("2026-11-05T15:40:29.873Z")

function context(answers: Record<string, unknown>) {
  const calls: { method: string; params?: Record<string, unknown> }[] = []
  const order: string[] = []
  const ctx: SessionContext = {
    request: vi.fn(async (method: string, params?: Record<string, unknown>, opts?: { onAnswer?: (a: { ok: boolean; result?: unknown }) => void }) => {
      calls.push({ method, params })
      order.push(method)
      const result = answers[method] ?? {}
      opts?.onAnswer?.({ ok: true, result })
      return result
    }),
    cwd: "/workspace/sdpm/servers/local",
    setupTimeoutMs: 1000,
    waitForMcp: vi.fn(async (sessionId: string) => { order.push(`wait ${sessionId}`) }),
    clearMcp: vi.fn((sessionId: string) => { order.push(`clear ${sessionId}`) }),
  }
  return { ctx, calls, order }
}

afterEach(() => { vi.useRealTimers() })

describe("V3 adapter", () => {
  it("starts kiro-cli with --agent-engine v3", () => {
    expect(v3Adapter.spawnArgs("sdpm-orchestrator")).toEqual(["acp", "--agent-engine", "v3"])
  })

  it("reads the session capabilities, replay marking and extension methods from initialize", () => {
    expect(v3Adapter.capabilities({
      protocolVersion: 1,
      agentCapabilities: {
        loadSession: true,
        sessionCapabilities: { list: {}, close: {}, delete: {}, fork: { _meta: { kiro: { messageId: true } } } } as never,
        _meta: { kiro: { replayMarking: true, extensionMethods: ["_kiro/session/compact"] } },
      },
    })).toEqual({ session: { list: true, close: true, delete: true, fork: true }, replayMarking: true, extensionMethods: new Set(["_kiro/session/compact"]), steer: true })
  })
})

describe("V3Session", () => {
  it("asks session/new for the agent's mode and waits for its sdpm server", async () => {
    const { ctx, calls, order } = context({ "session/new": { sessionId: "sess_1", modes: MODES("sdpm-orchestrator") } })
    const session = new V3Session(ctx)
    await expect(session.newSession("sdpm-orchestrator")).resolves.toEqual({ sessionId: "sess_1" })
    expect(calls[0]).toEqual({ method: "session/new", params: { cwd: "/workspace/sdpm/servers/local", mcpServers: [], _meta: { kiro: { modeId: "sdpm-orchestrator" } } } })
    expect(order).toEqual(["session/new", "wait sess_1"])
    expect(session.cancelTargets()).toEqual(["sess_1"])
  })

  it("refuses a session V3 started in vibe, after waiting for its not_found", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const { ctx } = context({ "session/new": { sessionId: "sess_1", modes: MODES("vibe") } })
      const session = new V3Session(ctx)
      const pending = session.newSession("sdpm-orchestrator").catch((e: unknown) => e)
      await new Promise((r) => setImmediate(r))
      session.translate({ method: "_kiro/customAgent/not_found", params: { sessionId: "sess_1", requestedAgent: "sdpm-orchestrator", fallbackAgent: "vibe" } })
      expect(await pending).toMatchObject({ code: "agent_definition_rejected", message: expect.stringContaining("vibe") })
      expect(ctx.waitForMcp).not.toHaveBeenCalled()
    } finally {
      warn.mockRestore()
    }
  })

  it("opens a saved session with session/load alone; an older createdAt is resumed", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(LOAD_AT)
    const { ctx, calls, order } = context({ "session/load": { modes: MODES("sdpm-orchestrator"), _meta: { createdAt: "2026-11-05T15:39:59.645910+00:00" } } })
    const onReplay = vi.fn()
    await expect(new V3Session(ctx).openSession("52ba6221", "sdpm-orchestrator", { onReplay })).resolves.toEqual({ sessionId: "52ba6221", outcome: "resumed" })
    expect(calls[0]).toEqual({ method: "session/load", params: { sessionId: "52ba6221", cwd: "/workspace/sdpm/servers/local", mcpServers: [] } })
    expect(order).toEqual(["session/load", "wait 52ba6221"])
    expect(onReplay.mock.calls).toEqual([[0, false], [0, true]])
  })

  it("reports a load whose session V3 just created as created", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(LOAD_AT)
    const info = vi.spyOn(console, "info").mockImplementation(() => {})
    try {
      const { ctx } = context({ "session/load": { modes: MODES("sdpm-orchestrator"), _meta: { createdAt: "2026-11-05T15:40:29.873Z" } } })
      expect((await new V3Session(ctx).openSession("11111111", "sdpm-orchestrator")).outcome).toBe("created")
      const { ctx: earlier } = context({ "session/load": { modes: MODES("sdpm-orchestrator"), _meta: { createdAt: "2026-11-05T15:40:29.000Z" } } })
      expect((await new V3Session(earlier).openSession("11111111", "sdpm-orchestrator")).outcome).toBe("created")
    } finally {
      info.mockRestore()
    }
  })

  it("treats a load without a readable createdAt as resumed, with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const { ctx } = context({ "session/load": { modes: MODES("sdpm-orchestrator") } })
      expect((await new V3Session(ctx).openSession("s", "sdpm-orchestrator")).outcome).toBe("resumed")
      expect(warn).toHaveBeenCalledOnce()
    } finally {
      warn.mockRestore()
    }
  })

  it("switches a loaded session in another mode to the agent's, after clearing its MCP record", async () => {
    const { ctx, calls, order } = context({ "session/load": { modes: MODES("sdpm-style"), _meta: { createdAt: "2026-01-01T00:00:00Z" } } })
    const onSwitching = vi.fn()
    await new V3Session(ctx).openSession("sess_ff", "sdpm-orchestrator", { onSwitching })
    expect(order).toEqual(["session/load", "clear sess_ff", "session/set_mode", "wait sess_ff"])
    expect(calls[1].params).toEqual({ sessionId: "sess_ff", modeId: "sdpm-orchestrator" })
    expect(onSwitching).toHaveBeenCalledOnce()
  })

  it("recognises ACP's auth required", () => {
    const session = new V3Session(context({}).ctx)
    expect(session.classifyError(new AcpRequestError({ code: -32000, message: "Authentication required. Not logged in." }))).toBe("auth_required")
    expect(session.classifyError(new AcpRequestError({ code: -32603, message: "Internal error" }))).toBeNull()
  })
})
