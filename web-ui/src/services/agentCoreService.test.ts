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
  resumeLocalAgent, setAgentConfig, steerAgentCore,
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

  it("routes a composer note to the session handler and task events to the parser", async () => {
    const onToolUse = vi.fn()
    const onSession = { onEvent: vi.fn() }
    const sessionId = sid()
    const done = invokeAgentCore("hi", sessionId, vi.fn(), "tok", "u1", onToolUse, undefined, "spec",
      undefined, undefined, undefined, onSession)
    const ws = FakeWebSocket.last()
    ws.open()
    const prompt = ws.ofType("prompt")[0]
    ws.receive({ ctl: "accepted", id: prompt.id, as: "turn", head: 2 })
    const note = { composerNote: { toolUseId: "c1", group: 1, slugs: "a", text: "done" } }
    ws.receive({ batch: [
      busy(1), { seq: 2, ev: { turn: { id: prompt.id, why: "prompt", text: "hi" } } },
      { seq: 3, ev: { taskStart: { toolUseId: "c1", name: "compose_slides", taskId: "t" } } },
      { seq: 4, ev: { turnEnd: { id: prompt.id, how: "finished" } } },
      { seq: 5, ev: note },
    ] })
    expect(onSession.onEvent).toHaveBeenCalledWith(note, { own: false })
    expect(onToolUse).toHaveBeenCalledWith("compose_slides", expect.objectContaining({ taskStarted: true }))
    let settled = false
    void done.then(() => { settled = true })
    await vi.advanceTimersByTimeAsync(0)
    expect(settled).toBe(false)
    ws.receive(idle(6))
    await expect(done).resolves.toBe("")
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

  it.each([
    ["the replay of the work that ended", { working: false, head: 5, period_start: 1, replay_from: 4, complete: true }, [text(4, " world"), idle(5)], "Hello world"],
    ["no replay when the process is gone", { working: false, head: 0, period_start: 1, replay_from: 1, complete: true }, [], "Hello"],
  ])("resolves after a reconnect that finds the work over: %s", async (_name, ack, replay, expected) => {
    const { done, ws } = startInvoke(sid())
    ws.receive(text(3, "Hello"))
    ws.drop()
    await vi.advanceTimersByTimeAsync(1000)
    const ws2 = FakeWebSocket.last()
    ws2.open()
    expect(ws2.messages()[0]).toEqual({ type: "resume", from_seq: 3 })
    ws2.receive({ ctl: "resumeAck", ...ack })
    if (replay.length) {
      expect(ws2.closedWith).toBeUndefined()
      ws2.receive({ batch: replay })
    }
    await expect(done).resolves.toBe(expected)
    expect(ws2.closedWith).toBe(1000)
  })

  it("uses the Local API route in Local mode", async () => {
    mode.local = true
    fetchMock.mockResolvedValueOnce(new Response("data: {\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"x\"}}}}\n"))
    await expect(invokeAgentCore("hi", "L1", vi.fn(), undefined, undefined, vi.fn())).resolves.toBe("x")
    expect(fetchMock.mock.calls[0][0]).toBe("/api/agent/invoke")
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it("hands a Local stream's steer events to onSession instead of the parser", async () => {
    mode.local = true
    const lines = [
      "data: {\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"one \"}}}}",
      "data: {\"steer\":{\"id\":\"m1\",\"text\":\"stop\",\"state\":\"accepted\"}}",
      "data: {\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"STOPPED\"}}}}",
      "data: {\"steer\":{\"id\":\"m1\",\"state\":\"delivered\"}}",
    ]
    fetchMock.mockResolvedValueOnce(new Response(lines.join("\n") + "\n"))
    const onEvent = vi.fn()
    const done = invokeAgentCore("hi", "L1", vi.fn(), undefined, undefined, vi.fn(), undefined, "spec", undefined, undefined, undefined, { onEvent })
    await expect(done).resolves.toBe("one STOPPED")
    expect(onEvent.mock.calls).toEqual([
      [{ steer: { id: "m1", text: "stop", state: "accepted" } }, { own: true }],
      [{ steer: { id: "m1", state: "delivered" } }, { own: true }],
    ])
  })

  it("hands a Local stream's notice to the session events", async () => {
    mode.local = true
    fetchMock.mockResolvedValueOnce(new Response(
      "id: 0\ndata: {\"notice\":{\"code\":\"context_not_carried_over\"}}\n\n" +
      "id: 1\ndata: {\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"x\"}}}}\n\n",
    ))
    const onEvent = vi.fn()
    await expect(invokeAgentCore("hi", "L1", vi.fn(), undefined, undefined, vi.fn(), undefined, "spec", "d1", undefined, undefined, { onEvent })).resolves.toBe("x")
    expect(onEvent).toHaveBeenCalledWith({ localNotice: "context_not_carried_over" }, { own: true })
  })

  it("hands a Local stream's period events to onSession and task events to the parser", async () => {
    mode.local = true
    const lines = [
      "data: {\"work\":{\"state\":\"busy\"}}",
      "data: {\"turn\":{\"id\":\"t1\",\"why\":\"prompt\",\"text\":\"hi\"}}",
      "data: {\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"x\"}}}}",
      "data: {\"taskStart\":{\"toolUseId\":\"c1\",\"name\":\"compose_slides\",\"taskId\":\"k\"}}",
      "data: {\"turnEnd\":{\"id\":\"t1\",\"how\":\"finished\"}}",
      "data: {\"work\":{\"state\":\"idle\",\"how\":\"finished\"}}",
    ]
    fetchMock.mockResolvedValueOnce(new Response(lines.join("\n") + "\n"))
    const onEvent = vi.fn()
    const onToolUse = vi.fn()
    await expect(invokeAgentCore("hi", "L1", vi.fn(), undefined, undefined, onToolUse, undefined, "spec", undefined, undefined, undefined, { onEvent })).resolves.toBe("x")
    expect(onEvent.mock.calls).toEqual([
      [{ work: { state: "busy" } }, { own: true }],
      [{ turn: { id: "t1", why: "prompt", text: "hi" } }, { own: true }],
      [{ turnEnd: { id: "t1", how: "finished" } }, { own: true }],
      [{ work: { state: "idle", how: "finished" } }, { own: true }],
    ])
    expect(onToolUse).toHaveBeenCalledWith("compose_slides", expect.objectContaining({ taskStarted: true }))
  })
})

describe("resumeLocalAgent", () => {
  beforeEach(() => { mode.local = true })
  const sse = (lines: string[]) => new Response(lines.map((l, i) => `id: ${i + 1}\ndata: ${l}\n\n`).join(""), { headers: { "Content-Type": "text/event-stream" } })

  it("answers not working when nothing runs, and calls no parser callback", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ running: false }))
    const handlers = { onResumeAck: vi.fn(), onStreamUpdate: vi.fn(), onToolUse: vi.fn(), onSession: { onEvent: vi.fn() } }
    await expect(resumeLocalAgent("a b", handlers)).resolves.toEqual({ working: false, completion: "" })
    expect(handlers.onResumeAck).toHaveBeenCalledWith({ working: false })
    expect(handlers.onStreamUpdate).not.toHaveBeenCalled()
    expect(handlers.onToolUse).not.toHaveBeenCalled()
    expect(handlers.onSession.onEvent).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls[0][0]).toBe("/api/agent/stream?sessionId=a%20b")
    expect(fetchMock.mock.calls[0][1].headers).toEqual({})
  })

  it("follows a period: acks working first, routes its events, and shows a failed turn in the reply", async () => {
    fetchMock.mockResolvedValueOnce(sse([
      "{\"turn\":{\"id\":\"t1\",\"why\":\"prompt\",\"text\":\"hi\"}}",
      "{\"event\":{\"contentBlockDelta\":{\"delta\":{\"text\":\"part \"}}}}",
      "{\"status\":\"error\",\"error\":\"boom\",\"code\":\"agent_exited\"}",
    ]))
    const order: string[] = []
    const onResumeAck = vi.fn(() => { order.push("ack") })
    const onEvent = vi.fn(() => { order.push("event") })
    const onStreamUpdate = vi.fn()
    const result = await resumeLocalAgent("L1", { onResumeAck, onStreamUpdate, onToolUse: vi.fn(), onSession: { onEvent } }, { lastEventId: 7 })
    expect(onResumeAck).toHaveBeenCalledWith({ working: true })
    expect(order[0]).toBe("ack")
    expect(onEvent).toHaveBeenCalledWith({ turn: { id: "t1", why: "prompt", text: "hi" } }, { own: false })
    expect(onStreamUpdate).toHaveBeenCalledWith("part ")
    expect(result.working).toBe(true)
    expect(result.completion.startsWith("part \n\n⚠ ")).toBe(true)
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ "Last-Event-ID": "7" })
  })

  it.each([
    ["an error status", () => Response.json({ error: "sessionId required" }, { status: 400 })],
    ["a body that is not JSON", () => new Response("<html>", { status: 200 })],
    ["JSON that is not {running: false}", () => Response.json({ ok: true })],
  ])("rejects on %s: a failed request says nothing about the work", async (_name, answer) => {
    fetchMock.mockResolvedValueOnce(answer())
    const onResumeAck = vi.fn()
    await expect(resumeLocalAgent("L1", { onResumeAck })).rejects.toThrow("Local stream error")
    expect(onResumeAck).not.toHaveBeenCalled()
  })

  it("rejects with an AbortError when its signal aborts", async () => {
    const controller = new AbortController()
    fetchMock.mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
    }))
    const done = resumeLocalAgent("L1", {}, { signal: controller.signal })
    controller.abort()
    await expect(done).rejects.toMatchObject({ name: "AbortError" })
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

  it("replays from the start when the deck opens again while the first follower still follows", async () => {
    const sessionId = sid()
    const first = startInvoke(sessionId)
    first.ws.receive(text(3, "Hel"))
    const firstDone = first.done.catch((err: unknown) => err)
    const onStreamUpdate = vi.fn()
    const onSession = { onEvent: vi.fn() }
    const done = resumeAgentCore(sessionId, "tok", 0, { onResumeAck: vi.fn(), onStreamUpdate, onToolUse: vi.fn(), onSession })
    // The superseded follower detaches without an error the chat would show.
    expect(await firstDone).toMatchObject({ name: "AbortError" })
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(first.ws.ofType("resume")).toEqual([{ type: "resume", from_seq: 0 }])
    // Live output before the ack comes again in the replay.
    first.ws.receive(text(4, "lo"))
    expect(onStreamUpdate).not.toHaveBeenCalled()
    first.ws.receive({ ctl: "resumeAck", working: true, head: 4, period_start: 1, replay_from: 1, complete: true })
    first.ws.receive({ batch: [busy(1), { seq: 2, ev: { turn: { id: first.promptId, why: "prompt", text: "hi" } } }, text(3, "Hel"), text(4, "lo")] })
    expect(onSession.onEvent).toHaveBeenCalledWith({ turn: { id: first.promptId, why: "prompt", text: "hi" } }, { own: true })
    expect(onStreamUpdate).toHaveBeenLastCalledWith("Hello")
    first.ws.receive(idle(5))
    await expect(done).resolves.toEqual({ working: true, completion: "Hello" })
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
