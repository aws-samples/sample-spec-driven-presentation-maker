// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { FakeWebSocket } from "@/test/fakeWebSocket"

const mode = vi.hoisted(() => ({ local: false }))
vi.mock("@/lib/mode", () => ({
  get IS_LOCAL() { return mode.local },
}))

import {
  cancelAgentCore, generateSessionId, invokeAgentCore, prepareAgentCore, resumeAgentCore,
  setAgentConfig, steerAgentCore,
} from "./agentCoreService"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/sdpm_agent-x"

describe("generateSessionId", () => {
  afterEach(() => { mode.local = false })

  it("carries the owner prefix in Cloud mode", () => {
    const id = generateSessionId("user-1")
    expect(id.startsWith("c6c289e49e9c05b2-")).toBe(true)
    expect(id.slice(17)).toMatch(UUID)
  })

  it("stays a plain UUID in Local mode", () => {
    mode.local = true
    expect(generateSessionId("user-1")).toMatch(UUID)
  })
})

// -- Cloud session connection ------------------------------------------------------

let n = 0
const sid = () => `sess-${++n}`
const text = (seq: number, t: string) => ({ seq, ev: { event: { contentBlockDelta: { delta: { text: t } } } } })
const busy = (seq: number) => ({ seq, ev: { work: { state: "busy" } } })
const idle = (seq: number) => ({ seq, ev: { work: { state: "idle", how: "finished" } } })

/** Start an invoke and accept its prompt as a turn; returns the socket and the prompt id. */
function startInvoke(sessionId: string, onUpdate = vi.fn(), onSession = { onEvent: vi.fn() }) {
  const done = invokeAgentCore("hi", sessionId, onUpdate, "tok", "u1", vi.fn(), undefined, "spec",
    undefined, undefined, undefined, onSession)
  const ws = FakeWebSocket.last()
  ws.open()
  const prompt = ws.ofType("prompt")[0]
  ws.receive({ ctl: "accepted", id: prompt.id, as: "turn", head: 2 })
  ws.receive({ batch: [busy(1), { seq: 2, ev: { turn: { id: prompt.id, why: "prompt", text: "hi" } } }] })
  return { done, ws, promptId: prompt.id as string, onUpdate, onSession }
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal("WebSocket", FakeWebSocket)
  fetchMock = vi.fn(async () => new Response("{}"))
  vi.stubGlobal("fetch", fetchMock)
  FakeWebSocket.reset()
  localStorage.clear()
  setAgentConfig(ARN, "us-east-1")
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  mode.local = false
})

describe("invokeAgentCore (Cloud)", () => {
  it("opens the session's /ws and sends the prompt", () => {
    const sessionId = sid()
    void invokeAgentCore("hi", sessionId, vi.fn(), "tok", "u1", vi.fn(), undefined, "vibe")
    const ws = FakeWebSocket.last()
    expect(ws.url).toBe(
      `wss://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/${encodeURIComponent(ARN)}/ws`
      + `?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=${sessionId}`,
    )
    ws.open()
    expect(ws.ofType("prompt")[0]).toMatchObject({ prompt: "hi", mode: "vibe" })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("streams text and session events and resolves when the session goes idle", async () => {
    const { done, ws, promptId, onUpdate, onSession } = startInvoke(sid())
    ws.receive({ batch: [text(3, "Hel"), text(4, "lo")] })
    expect(onUpdate).toHaveBeenLastCalledWith("Hello")
    expect(onSession.onEvent).toHaveBeenCalledWith({ turn: { id: promptId, why: "prompt", text: "hi" } }, { own: true })
    ws.receive(idle(5))
    await expect(done).resolves.toBe("Hello")
    expect(ws.closedWith).toBe(1000)
  })

  it("rejects on an error before the prompt was accepted", async () => {
    const done = invokeAgentCore("hi", sid(), vi.fn(), "tok", "u1", vi.fn())
    const ws = FakeWebSocket.last()
    ws.open()
    ws.receive({ ctl: "error", code: "auth", error: "Session not available" })
    await expect(done).rejects.toMatchObject({ message: "Session not available", code: "auth" })
  })

  it("rejects when the connection fails before the prompt was accepted", async () => {
    const done = invokeAgentCore("hi", sid(), vi.fn(), "tok", "u1", vi.fn())
    FakeWebSocket.last().drop()
    await expect(done).rejects.toThrow()
  })

  it("keeps following when a steer that raced the end of the work starts a new turn", async () => {
    const sessionId = sid()
    const { done, ws } = startInvoke(sessionId)
    let settled = false
    void done.then(() => { settled = true })
    const steer = steerAgentCore(sessionId, "and more", "tok", "s1")
    ws.receive(idle(3))
    ws.receive({ ctl: "accepted", id: "s1", as: "turn", head: 5 })
    await expect(steer).resolves.toEqual({ id: "s1", as: "turn" })
    expect(settled).toBe(false)
    ws.receive({ batch: [busy(4), { seq: 5, ev: { turn: { id: "s1", why: "prompt", text: "and more" } } }, text(6, "ok"), idle(7)] })
    await expect(done).resolves.toBe("ok")
  })

  it("uses the Local API route in Local mode", async () => {
    mode.local = true
    fetchMock.mockResolvedValueOnce(new Response("data: {\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"x\"}}}}\n"))
    await expect(invokeAgentCore("hi", "L1", vi.fn(), undefined, undefined, vi.fn())).resolves.toBe("x")
    expect(fetchMock.mock.calls[0][0]).toBe("/api/agent/invoke")
    expect(FakeWebSocket.instances).toHaveLength(0)
  })
})

describe("steerAgentCore", () => {
  it("sends a steer over the open socket and resolves when it is accepted", async () => {
    const sessionId = sid()
    const { ws } = startInvoke(sessionId)
    const steer = steerAgentCore(sessionId, "also this", "tok", "s1")
    expect(ws.ofType("steer")).toEqual([{ type: "steer", id: "s1", text: "also this" }])
    ws.receive({ ctl: "accepted", id: "s1", as: "steer", head: 3 })
    await expect(steer).resolves.toEqual({ id: "s1", as: "steer" })
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("rejects when the steer is not acknowledged within 3 s", async () => {
    const sessionId = sid()
    startInvoke(sessionId)
    const steer = steerAgentCore(sessionId, "also this", "tok", "s1")
    const check = expect(steer).rejects.toThrow()
    vi.advanceTimersByTime(3000)
    await check
  })
})

describe("cancelAgentCore", () => {
  it("falls back to StopRuntimeSession when the cancel is not acknowledged within 3 s", async () => {
    const sessionId = sid()
    const { done, ws } = startInvoke(sessionId)
    const stop = cancelAgentCore(sessionId, "tok")
    expect(ws.ofType("cancel")).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(3000)
    await expect(stop).resolves.toBe("fallback")
    await expect(done).resolves.toBe("")
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain("/stopruntimesession?qualifier=DEFAULT")
    expect(ws.closedWith).toBe(1000)
  })

  it("does not call StopRuntimeSession when the cancel is acknowledged", async () => {
    const sessionId = sid()
    const { done, ws } = startInvoke(sessionId)
    const stop = cancelAgentCore(sessionId, "tok")
    const cancel = ws.ofType("cancel")[0]
    ws.receive({ ctl: "cancelAck", id: cancel.id, result: "cancelling" })
    ws.receive({ batch: [{ seq: 3, ev: { turnEnd: { id: "x", how: "cancelled" } } }, { seq: 4, ev: { work: { state: "idle", how: "cancelled" } } }] })
    await expect(stop).resolves.toBe("stopped")
    await expect(done).resolves.toBe("")
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("shows stopped 2 s after the acknowledgement when the session has not gone idle", async () => {
    const sessionId = sid()
    const { done, ws } = startInvoke(sessionId)
    const stop = cancelAgentCore(sessionId, "tok")
    ws.receive({ ctl: "cancelAck", id: ws.ofType("cancel")[0].id, result: "cancelling" })
    await vi.advanceTimersByTimeAsync(2000)
    await expect(stop).resolves.toBe("stopped")
    await expect(done).resolves.toBe("")
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe("resumeAgentCore", () => {
  it("replays and follows a working session until it goes idle", async () => {
    const onResumeAck = vi.fn()
    const onStreamUpdate = vi.fn()
    const done = resumeAgentCore(sid(), "tok", 0, { onResumeAck, onStreamUpdate, onToolUse: vi.fn() })
    const ws = FakeWebSocket.last()
    ws.open()
    expect(ws.messages()).toEqual([{ type: "resume", from_seq: 0 }])
    ws.receive({ ctl: "resumeAck", working: true, head: 3, period_start: 1, replay_from: 1, complete: true })
    ws.receive({ batch: [busy(1), text(2, "a"), text(3, "b")] })
    ws.receive(idle(4))
    await expect(done).resolves.toEqual({ working: true, completion: "ab" })
    expect(onResumeAck).toHaveBeenCalledWith(expect.objectContaining({ working: true }))
  })

  it("closes at once when the session is not working", async () => {
    const done = resumeAgentCore(sid(), "tok", 0, { onStreamUpdate: vi.fn() })
    const ws = FakeWebSocket.last()
    ws.open()
    ws.receive({ ctl: "resumeAck", working: false, head: 0, period_start: 1, replay_from: 1, complete: true })
    await expect(done).resolves.toEqual({ working: false, completion: "" })
    expect(ws.closedWith).toBe(1000)
  })
})

describe("prepareAgentCore", () => {
  it("sends prepare, carries a send before ready on the same socket and closes after ready when idle", async () => {
    const sessionId = sid()
    const ready = prepareAgentCore(sessionId, "tok", "spec")
    const ws = FakeWebSocket.last()
    ws.open()
    expect(ws.messages()).toEqual([{ type: "prepare", mode: "spec" }])
    ws.receive({ ctl: "prepareAck" })
    expect(ws.closedWith).toBeUndefined()
    ws.receive({ ctl: "ready", mcp_status: [{ name: "pm", status: "connected" }] })
    await expect(ready).resolves.toEqual([{ name: "pm", status: "connected" }])
    expect(ws.closedWith).toBe(1000)

    const second = prepareAgentCore(sessionId, "tok", "spec")
    const ws2 = FakeWebSocket.last()
    ws2.open()
    ws2.receive({ ctl: "prepareAck" })
    void invokeAgentCore("hi", sessionId, vi.fn(), "tok", "u1", vi.fn())
    expect(FakeWebSocket.last()).toBe(ws2)
    expect(ws2.ofType("prompt")).toHaveLength(1)
    const prompt = ws2.ofType("prompt")[0]
    ws2.receive({ ctl: "accepted", id: prompt.id, as: "turn", head: 6 })
    ws2.receive({ ctl: "ready", mcp_status: [] })
    await second
    expect(ws2.closedWith).toBeUndefined()
  })

  it("does nothing in Local mode", async () => {
    mode.local = true
    await expect(prepareAgentCore("L1", "tok", "spec")).resolves.toBeUndefined()
    expect(FakeWebSocket.instances).toHaveLength(0)
  })
})
