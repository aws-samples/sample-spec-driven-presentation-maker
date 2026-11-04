// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { FakeWebSocket } from "@/test/fakeWebSocket"
import { readSessionState } from "@/lib/sessionState"
import { PING_INTERVAL_MS, SessionSocket, SUBPROTOCOL, base64Url, type SessionItem, type SessionSocketListener } from "./sessionSocket"

const TOKEN = "eyJhbGciOi.eyJzdWIiOiJ1MSJ9.sig+/="

const created: SessionSocket[] = []

function setup(sessionId = `s-${Math.random()}`) {
  const items: SessionItem[] = []
  const ctls: { ctl: string; answered?: string }[] = []
  const reconnecting: boolean[] = []
  const closed: Parameters<NonNullable<SessionSocketListener["onClosed"]>>[0][] = []
  const socket = new SessionSocket({
    url: "wss://example/ws",
    sessionId,
    getToken: () => TOKEN,
    listener: {
      onItem: (item) => items.push(item),
      onCtl: (ctl, answered) => ctls.push({ ctl: ctl.ctl, answered }),
      onReconnecting: (active) => reconnecting.push(active),
      onClosed: (info) => closed.push(info),
    },
  })
  created.push(socket)
  return { socket, items, ctls, reconnecting, closed, sessionId }
}

const busy = (seq: number) => ({ seq, ev: { work: { state: "busy" } } })
const idle = (seq: number) => ({ seq, ev: { work: { state: "idle", how: "finished" } } })
const text = (seq: number, t: string) => ({ seq, ev: { event: { contentBlockDelta: { delta: { text: t } } } } })

/** Send a prompt on a new socket and let the server accept it as a turn. */
function startWork(s: ReturnType<typeof setup>) {
  s.socket.send({ type: "prompt", id: "p1", prompt: "hi" })
  const ws = FakeWebSocket.last()
  ws.open()
  ws.receive({ ctl: "accepted", id: "p1", as: "turn", head: 2 })
  ws.receive({ batch: [busy(1), { seq: 2, ev: { turn: { id: "p1", why: "prompt", text: "hi" } } }] })
  return ws
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal("WebSocket", FakeWebSocket)
  FakeWebSocket.reset()
  localStorage.clear()
})

afterEach(() => {
  for (const socket of created.splice(0)) socket.close()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("SessionSocket", () => {
  it("opens with the token as a base64url subprotocol plus the bare name", () => {
    const s = setup()
    expect(FakeWebSocket.instances).toHaveLength(0)
    s.socket.send({ type: "ping" })
    const ws = FakeWebSocket.last()
    expect(ws.url).toBe("wss://example/ws")
    expect(ws.protocols).toEqual([`${SUBPROTOCOL}.${base64Url(TOKEN)}`, SUBPROTOCOL])
    expect(base64Url(TOKEN)).not.toMatch(/[+/=]/)
  })

  it("speaks first: the message goes out as soon as the connection opens", () => {
    const s = setup()
    s.socket.send({ type: "prompt", id: "p1", prompt: "hi" })
    const ws = FakeWebSocket.last()
    expect(ws.sent).toEqual([])
    ws.open()
    expect(ws.ofType("prompt")).toEqual([{ type: "prompt", id: "p1", prompt: "hi" }])
  })

  it("delivers batch and chunk frames as items in seq order and drops a seq seen before", () => {
    const s = setup()
    const ws = startWork(s)
    const big = JSON.stringify(text(4, "x".repeat(50)))
    ws.receive(text(3, "a"))
    ws.receive({ chunk: "c1", i: 1, n: 2, data: big.slice(20) })
    ws.receive({ chunk: "c1", i: 0, n: 2, data: big.slice(0, 20) })
    ws.receive({ batch: [text(3, "dup"), text(5, "b")] })
    expect(s.items.map((i) => i.seq)).toEqual([1, 2, 3, 4, 5])
    expect(s.items[3].ev).toEqual(text(4, "x".repeat(50)).ev)
    expect(s.socket.lastSeq).toBe(5)
  })

  it("pings every 30 s only while the session works, and closes when it goes idle", () => {
    const s = setup()
    s.socket.send({ type: "prepare" })
    s.socket.hold()
    const ws = FakeWebSocket.last()
    ws.open()
    ws.receive({ ctl: "prepareAck" })
    vi.advanceTimersByTime(PING_INTERVAL_MS * 2)
    expect(ws.ofType("ping")).toHaveLength(0)
    s.socket.send({ type: "prompt", id: "p1", prompt: "hi" })
    ws.receive({ ctl: "accepted", id: "p1", as: "turn", head: 2 })
    ws.receive(busy(1))
    vi.advanceTimersByTime(PING_INTERVAL_MS * 2)
    expect(ws.ofType("ping")).toHaveLength(2)
    s.socket.release()
    ws.receive(idle(2))
    expect(ws.closedWith).toBe(1000)
    vi.advanceTimersByTime(PING_INTERVAL_MS * 2)
    expect(ws.ofType("ping")).toHaveLength(2)
  })

  it("stays open at idle while a message is unanswered, and follows the turn it started", () => {
    const s = setup()
    const ws = startWork(s)
    s.socket.send({ type: "steer", id: "s1", text: "more" })
    ws.receive(idle(3))
    expect(ws.closedWith).toBeUndefined()
    ws.receive({ ctl: "accepted", id: "s1", as: "turn", head: 5 })
    expect(s.socket.working).toBe(true)
    ws.receive({ batch: [busy(4), idle(5)] })
    expect(ws.closedWith).toBe(1000)
  })

  it("reconnects with resume from the last seq after an unexpected close while working", () => {
    const s = setup()
    const ws = startWork(s)
    ws.receive(text(3, "a"))
    ws.drop()
    expect(s.reconnecting).toEqual([true])
    expect(s.closed[0]).toMatchObject({ reconnecting: true, gaveUp: false })
    vi.advanceTimersByTime(1000)
    const ws2 = FakeWebSocket.last()
    expect(ws2).not.toBe(ws)
    ws2.open()
    expect(ws2.messages()[0]).toEqual({ type: "resume", from_seq: 3 })
    ws2.receive({ ctl: "resumeAck", working: true, head: 4, period_start: 1, replay_from: 4, complete: true })
    expect(s.reconnecting).toEqual([true, false])
    ws2.receive(text(4, "b"))
    expect(s.items.map((i) => i.seq)).toEqual([1, 2, 3, 4])
  })

  it("delivers the replay of a resume from 0 on an open connection that already saw it", () => {
    const s = setup()
    const ws = startWork(s)
    ws.receive(text(3, "a"))
    s.socket.send({ type: "resume", from_seq: 0 })
    ws.receive({ ctl: "resumeAck", working: true, head: 3, period_start: 1, replay_from: 1, complete: true })
    ws.receive({ batch: [busy(1), { seq: 2, ev: { turn: { id: "p1", why: "prompt", text: "hi" } } }, text(3, "a")] })
    expect(s.items.map((i) => i.seq)).toEqual([1, 2, 3, 1, 2, 3])
    expect(s.socket.lastSeq).toBe(3)
  })

  it("sends only the page's resume when one is queued during a reconnect, and pings again after it", () => {
    const s = setup()
    const ws = startWork(s)
    ws.receive(text(3, "a"))
    ws.drop()
    s.socket.send({ type: "resume", from_seq: 0 })
    vi.advanceTimersByTime(1000)
    const ws2 = FakeWebSocket.last()
    ws2.open()
    expect(ws2.ofType("resume")).toEqual([{ type: "resume", from_seq: 0 }])
    ws2.receive({ ctl: "resumeAck", working: true, head: 3, period_start: 1, replay_from: 1, complete: true })
    vi.advanceTimersByTime(PING_INTERVAL_MS)
    expect(ws2.ofType("ping")).toHaveLength(1)
  })

  it("backs off and gives up after five attempts", () => {
    const s = setup()
    startWork(s).drop()
    for (const delay of [1000, 2000, 5000, 10_000, 10_000]) {
      vi.advanceTimersByTime(delay)
      FakeWebSocket.last().drop()
    }
    expect(FakeWebSocket.instances).toHaveLength(6)
    expect(s.closed.at(-1)).toMatchObject({ reconnecting: false, gaveUp: true })
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(6)
  })

  it("does not reconnect after a close while idle, or after a refusal", () => {
    const idleCase = setup()
    idleCase.socket.send({ type: "ping" })
    FakeWebSocket.last().open()
    FakeWebSocket.last().drop()
    vi.advanceTimersByTime(30_000)
    expect(FakeWebSocket.instances).toHaveLength(1)

    const refused = setup()
    const ws = startWork(refused)
    ws.drop(4403)
    vi.advanceTimersByTime(30_000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it("reconnects at once when the tab becomes visible while working", () => {
    const s = setup()
    startWork(s).drop()
    expect(FakeWebSocket.instances).toHaveLength(1)
    document.dispatchEvent(new Event("visibilitychange"))
    expect(FakeWebSocket.instances).toHaveLength(2)
    FakeWebSocket.last().open()
    expect(FakeWebSocket.last().messages()[0]).toEqual({ type: "resume", from_seq: 2 })
  })

  it("keeps the last known state and seq in localStorage", () => {
    const s = setup()
    const ws = startWork(s)
    expect(readSessionState(s.sessionId)).toMatchObject({ state: "working" })
    ws.receive(text(3, "a"))
    vi.advanceTimersByTime(1000)
    expect(readSessionState(s.sessionId)).toMatchObject({ state: "working", lastSeq: 3 })
    ws.receive(idle(4))
    expect(readSessionState(s.sessionId)).toMatchObject({ state: "idle", lastSeq: 4 })
  })

  it("names the message a control message answers", () => {
    const s = setup()
    s.socket.send({ type: "resume", from_seq: 0 })
    const ws = FakeWebSocket.last()
    ws.open()
    ws.receive({ ctl: "resumeAck", working: false, head: 0, period_start: 1, replay_from: 1, complete: true })
    expect(s.ctls).toEqual([{ ctl: "resumeAck", answered: "resume" }])
    expect(ws.closedWith).toBe(1000)
  })
})
