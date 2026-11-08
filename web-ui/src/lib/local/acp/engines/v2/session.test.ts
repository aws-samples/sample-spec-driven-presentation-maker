// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V2 session: kiro-cli starts with `--agent <name>`, session/new carries no agent field and
 * must answer the agent's mode, then the sdpm server is waited for; opening a saved session is
 * session/new then session/load (prompts go to the loaded id), a `Session not found` keeps the
 * new session as `created`, another mode is switched with set_mode after the session's MCP
 * record was cleared; Stop cancels the main session and this turn's sub-agent sessions; the
 * models come from session/new and a load's answer, without `[Internal]` / `[Deprecated]` ones,
 * and session/set_model changes the model (V2 has no effort); the lock and auth errors are
 * recognised. A fork copies the stored session's files and opens the copy; a copy V2 cannot
 * read is `created` under the copy's id; `discardFork` removes only a copy this session made.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { describe, expect, it, vi } from "vitest"

import { AgentStartError } from "../../../turnErrors"
import type { SessionContext } from "../../engine"
import { AcpRequestError } from "../../transport"
import { v2Adapter } from "."
import { V2Session } from "./session"

const MODES = (current: string) => ({ currentModeId: current, availableModes: [{ id: "sdpm-orchestrator", name: "o" }, { id: "sdpm-style", name: "s" }] })

function context(answers: Record<string, unknown | ((params: Record<string, unknown>) => unknown)>, env: Record<string, string> = {}) {
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
    env: env as unknown as NodeJS.ProcessEnv,
    setupTimeoutMs: 1000,
    hostAgent: "sdpm-orchestrator",
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
    expect(session.models()).toEqual({ current: "auto", available: [{ modelId: "auto", name: "auto" }], effort: null })
    expect(session.cancelTargets()).toEqual(["K1"])
  })

  it("takes the models of a load's answer, which keep the session's model", async () => {
    const list = [
      { modelId: "auto", name: "auto" },
      { modelId: "claude-haiku-4.5", name: "claude-haiku-4.5", description: "Haiku" },
      { modelId: "grok-4.7", name: "grok-4.7", description: "[Internal] Experimental" },
    ]
    const { ctx } = context({
      "session/new": { ...NEW, models: { currentModelId: "auto", availableModels: list } },
      "session/load": { modes: MODES("sdpm-orchestrator"), models: { currentModelId: "claude-haiku-4.5", availableModels: list } },
    })
    const session = new V2Session(ctx)
    await session.openSession("K9", "sdpm-orchestrator")
    expect(session.models()).toEqual({ current: "claude-haiku-4.5", available: list.slice(0, 2), effort: null })
  })

  it("changes the model with session/set_model and refuses an effort", async () => {
    const { ctx, calls } = context({ "session/new": { ...NEW, models: { currentModelId: "auto", availableModels: [{ modelId: "auto" }, { modelId: "m2" }] } } })
    const session = new V2Session(ctx)
    await session.newSession("sdpm-orchestrator")
    await session.setModel({ model: "m2" })
    expect(calls[1]).toEqual({ method: "session/set_model", params: { sessionId: "K1", modelId: "m2" } })
    expect(vi.mocked(ctx.request).mock.calls[1][2]).toEqual({ timeoutMs: 10_000 })
    expect(session.models()?.current).toBe("m2")
    await expect(session.setModel({ model: "auto", effort: "low" })).rejects.toThrow(/no effort/)
    expect(calls).toHaveLength(2)
  })

  it("opens another agent's session on a kiro-cli started for the orchestrator: set_mode, then the MCP wait", async () => {
    const { ctx, calls, order } = context({ "session/new": { sessionId: "K2", modes: { currentModeId: "sdpm-orchestrator", availableModes: [{ id: "sdpm-orchestrator", name: "o" }, { id: "sdpm-composer", name: "c" }] } } })
    await expect(new V2Session(ctx).newSession("sdpm-composer")).resolves.toEqual({ sessionId: "K2" })
    expect(calls.map((c) => c.method)).toEqual(["session/new", "session/set_mode"])
    expect(calls[1].params).toEqual({ sessionId: "K2", modeId: "sdpm-composer" })
    expect(order).toEqual(["session/new", "clear K2", "session/set_mode", "wait K2"])
  })

  it("refuses another agent's session when its kiro-cli does not list that agent", async () => {
    vi.useFakeTimers()
    try {
      const { ctx } = context({ "session/new": { sessionId: "K2", modes: MODES("sdpm-orchestrator") } })
      const pending = new V2Session(ctx).newSession("sdpm-composer").catch((e: unknown) => e)
      await vi.advanceTimersByTimeAsync(2000)
      expect(await pending).toMatchObject({ code: "agent_definition_rejected" })
      expect(ctx.waitForMcp).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("sends nothing to close or discard a session (V2 has neither)", async () => {
    const { ctx, calls } = context({ "session/new": NEW })
    const session = new V2Session(ctx)
    await session.newSession("sdpm-orchestrator")
    await session.close()
    await session.discard()
    expect(calls.map((c) => c.method)).toEqual(["session/new"])
  })

  it("refuses a session in another mode (kiro_default for an agent V2 did not find)", async () => {
    vi.useFakeTimers()
    try {
      // kiro_default is not the kiro-cli's own agent, even though every sdpm mode is listed.
      const { ctx } = context({ "session/new": { sessionId: "K1", modes: { currentModeId: "kiro_default", availableModes: [{ id: "sdpm-orchestrator", name: "o" }] } } })
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

  describe("forkSession", () => {
    const SOURCE = "11111111-1111-4111-8111-111111111111"

    function store() {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), "v2-fork-"))
      fs.writeFileSync(path.join(dir, `${SOURCE}.json`), JSON.stringify({ session_id: SOURCE, cwd: "/work/a", title: "T" })) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
      fs.writeFileSync(path.join(dir, `${SOURCE}.jsonl`), "") // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
      return dir
    }

    it("copies the stored session and opens the copy", async () => {
      const dir = store()
      try {
        const { ctx, calls, order } = context({ "session/new": NEW, "session/load": { modes: MODES("sdpm-orchestrator") } }, { SDPM_KIRO_SESSIONS_DIR: dir })
        const onCopying = vi.fn()
        const onForked = vi.fn()
        const forked = await new V2Session(ctx).forkSession(SOURCE, "sdpm-orchestrator", { onCopying, onForked })
        expect(forked.outcome).toBe("resumed")
        expect(forked.sessionId).not.toBe(SOURCE)
        expect(onCopying).toHaveBeenCalledOnce()
        expect(onForked).toHaveBeenCalledWith(forked.sessionId)
        expect(calls[1].params).toMatchObject({ sessionId: forked.sessionId })
        expect(order).toEqual(["session/new", "session/load", `wait ${forked.sessionId}`])
        expect(fs.readdirSync(dir).sort()).toEqual([`${SOURCE}.json`, `${SOURCE}.jsonl`, `${forked.sessionId}.json`, `${forked.sessionId}.jsonl`].sort())
      } finally {
        fs.rmSync(dir, { recursive: true, force: true })
      }
    })

    it("reports a copy V2 cannot read as created, under the copy's id", async () => {
      const dir = store()
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
      try {
        const { ctx } = context({
          "session/new": NEW,
          "session/load": () => { throw new AcpRequestError({ code: -32603, message: "Internal error", data: "Session not found: x" }) },
        }, { SDPM_KIRO_SESSIONS_DIR: dir })
        const forked = await new V2Session(ctx).forkSession(SOURCE, "sdpm-orchestrator")
        expect(forked.outcome).toBe("created")
        expect(forked.sessionId).not.toBe("K1")
      } finally {
        warn.mockRestore()
        fs.rmSync(dir, { recursive: true, force: true })
      }
    })

    it("discards only a copy it made", async () => {
      const dir = store()
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
      try {
        const { ctx } = context({ "session/new": NEW, "session/load": { modes: MODES("sdpm-orchestrator") } }, { SDPM_KIRO_SESSIONS_DIR: dir })
        const session = new V2Session(ctx)
        const { sessionId } = await session.forkSession(SOURCE, "sdpm-orchestrator")
        await session.discardFork(SOURCE)
        expect(warn).toHaveBeenCalledOnce()
        await session.discardFork(sessionId)
        expect(fs.readdirSync(dir).sort()).toEqual([`${SOURCE}.json`, `${SOURCE}.jsonl`])
      } finally {
        warn.mockRestore()
        fs.rmSync(dir, { recursive: true, force: true })
      }
    })
  })
})
