// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A chat (chat.ts) through the registry: its work period is numbered from 1 (`work` busy, `turn`,
 * the output, `turnEnd`, `work` idle, `end`), a listener and a reconnect see the same ids, and a
 * notice follows the `turn` event; a turn ends with the answer to its own session/prompt (result or
 * error), whatever the sub-agent sessions or other requests sent, or with agent_exited when
 * kiro-cli exits first, and a prompt during a turn is refused; a steer goes into the running turn
 * and is reported accepted, delivered (V2 by its text, V3 by its messageId, or sent as a follow-up
 * prompt of the same turn when the prompt ended before kiro-cli read it) or discarded when Stop or
 * an exit ends the turn first, and kiro-cli's queue is cleared; a kiro-cli without steering is
 * sent no further steer. While work holds the period (a fake hold here, web-2's compose task
 * later), a prompt or a steer starts a turn in it (the invoke replays from that turn), the second
 * turn's output follows a messageStart, and the Local server's own texts go in as a hidden steer,
 * a hidden turn, or wait for the next prompt (after Stop, without a period). Stop cancels the turn
 * and every hold, sends nothing that starts model work afterwards, and ends the period without a
 * hold that did not release within 5 s (dropped first). A chat whose kiro-cli exited reopens its
 * session on its next message. A V2 session another kiro-cli holds is refused with session_locked.
 * kiro-cli is replaced by the fake child (src/test/fakeKiro.ts).
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { BufferedEvent } from "./conversation/events"
import { FakeChild, settle } from "../../test/fakeKiro"
import { installFakeProcesses } from "../../test/fakeProcesses"

const { spawn, execFile, execFileSync } = vi.hoisted(() => ({ spawn: vi.fn(), execFile: vi.fn(), execFileSync: vi.fn() }))
vi.mock("child_process", () => ({ spawn, execFile, execFileSync, default: { spawn, execFile, execFileSync } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn(() => "d0") }))

const isEnd = (e: BufferedEvent) => e.event.kind === "end"
const payloadOf = (e: BufferedEvent) => e.event.payload as Record<string, unknown> | undefined
const steerOf = (e: BufferedEvent) => payloadOf(e)?.steer as { id: string; text?: string; state: string } | undefined

let children: FakeChild[]
let locked: Set<string>
let acp: typeof import("./acp-process")
let deckRoot: string
let configDir: string

beforeEach(async () => {
  deckRoot = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-chat-"))) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_DECK_ROOT", deckRoot)
  children = []
  locked = new Set()
  spawn.mockReset()
  installFakeProcesses({ spawn, execFile, execFileSync })
  spawn.mockImplementation((_command: string, args: string[]) => {
    const child = new FakeChild(`K${children.length + 1}`, locked, args)
    children.push(child)
    return child
  })
  configDir = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-acp-config-")) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", configDir)
  useEngine("v2") // the fake child speaks V2 unless a test chooses V3
  vi.resetModules()
  acp = await import("./acp-process")
})

afterEach(() => {
  for (const child of children) child.kill()
  vi.unstubAllEnvs()
  fs.rmSync(deckRoot, { recursive: true, force: true })
  fs.rmSync(configDir, { recursive: true, force: true })
})

/** Choose the engine the next kiro-cli starts on, as Settings does (acp-config.json). */
function useEngine(engine: "v2" | "v3") {
  fs.writeFileSync(path.join(configDir, "acp-config.json"), JSON.stringify({ version: 2, engine })) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
}

describe("turn state", () => {
  /** One turn on a session: prompt, optional sub-agents, then the prompt's answer. */
  async function turn(child: FakeChild, sessionId: string, subSessions: string[] = []) {
    const prompted = await acp.sendPrompt(sessionId, "build the deck")
    prompted.send()
    for (const sub of subSessions) child.runSubagent(sub)
    await settle()
    expect(acp.isSessionRunning(sessionId)).toBe(true)
    child.endTurn()
    await settle()
  }

  it("is no longer running once the prompt is answered after a turn that used sub-agents", async () => {
    await acp.createNewProcessFor("C1")
    await turn(children[0], "C1", ["S1", "S2"])
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(acp.isSessionRunning("K1")).toBe(false)

    // The next send goes through (no SessionBusyError → 409) and its turn also ends.
    await turn(children[0], "K1")
    expect(acp.isSessionRunning("K1")).toBe(false)
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("is no longer running after a turn on a session restored with session/load", async () => {
    await acp.openDeckSession("K9", "d9", "K9", "sdpm-orchestrator")
    await turn(children[0], "K9")
    expect(acp.isSessionRunning("K9")).toBe(false)
  })

  it("evicts the oldest idle process, including one whose last turn used sub-agents", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    try {
      vi.setSystemTime(1_000)
      for (const id of ["C1", "C2", "C3"]) await acp.createNewProcessFor(id)
      vi.setSystemTime(2_000)
      await turn(children[0], "C1", ["S1"])
      vi.setSystemTime(3_000)
      await turn(children[1], "C2")
      vi.setSystemTime(4_000)
      await turn(children[2], "C3")

      await acp.createNewProcessFor("C4")
      expect(children.map((c) => c.killed)).toEqual([true, false, false, false])
    } finally {
      vi.useRealTimers()
    }
  })

  it("cancel reaches the main session and the sub-agents still working, and ends the turn", async () => {
    await acp.createNewProcessFor("C1")
    const child = children[0]
    await turn(child, "C1", ["S1"])

    const prompted = await acp.sendPrompt("C1", "again")
    prompted.send()
    child.runSubagent("S2", false)
    await settle()
    acp.cancelSession("C1")
    expect(child.cancelled).toEqual(["K1", "S2"])

    child.endTurn("cancelled")
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(false)
    await expect(acp.sendPrompt("C1", "after cancel")).resolves.toMatchObject({ sessionId: "K1" })
  })

  it("ends the turn when session/prompt is answered with an error, and accepts the next send", async () => {
    await acp.createNewProcessFor("C1")
    const child = children[0]
    const prompted = await acp.sendPrompt("C1", "build the deck")
    const ends: BufferedEvent["event"][] = []
    prompted.subscribe((entry) => { if (isEnd(entry)) ends.push(entry.event) })
    prompted.send()
    child.runSubagent("S1")
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(true)

    child.failPrompt()
    await settle()
    expect(ends).toEqual([{ kind: "end", payload: { status: "error", error: "Internal error: model stream failed" } }])
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(acp.isSessionRunning("K1")).toBe(false)

    // No SessionBusyError (→ 409): the failed prompt released the session.
    await turn(child, "K1")
    expect(acp.isSessionRunning("K1")).toBe(false)
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("keeps the turn running when another request fails mid-turn, until the prompt is answered", async () => {
    await acp.createNewProcessFor("C1")
    const child = children[0]
    child.failing.add("_session/steer")
    const prompted = await acp.sendPrompt("C1", "build the deck")
    const ends: BufferedEvent["event"][] = []
    prompted.subscribe((entry) => { if (isEnd(entry)) ends.push(entry.event) })
    prompted.send()
    await settle()

    const { SteerRejectedError } = await import("./conversation/steer")
    await expect(acp.steerSession("C1", "m1", "also this")).rejects.toBeInstanceOf(SteerRejectedError)
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(true)
    expect(ends).toEqual([])
    await expect(acp.sendPrompt("C1", "again")).rejects.toThrow(/still answering/)

    child.endTurn()
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(ends).toEqual([{ kind: "end", stopReason: "end_turn" }])
  })

  it.each(["end_turn", "cancelled", "refusal", "max_tokens", "max_turn_requests"])("ends the turn with stopReason %s and buffers the end for reconnects", async (stopReason) => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "build the deck")
    prompted.send()
    await settle()
    children[0].endTurn(stopReason)
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(acp.getBufferedEvents("C1").at(-1)?.event).toMatchObject({ kind: "end", stopReason })
  })

  it("ends a running turn with agent_exited when kiro-cli exits, and forgets the process", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "build the deck")
    const seen: BufferedEvent[] = []
    prompted.subscribe((entry) => { seen.push(entry) })
    prompted.send()
    await settle()

    children[0].kill()
    await settle()
    expect(seen.at(-1)?.event).toMatchObject({ kind: "end", payload: { status: "error", code: "agent_exited" } })
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.hasProcess("K1")).toBe(false)
  })

  it("sends no turn event when an idle process exits", async () => {
    await acp.createNewProcessFor("C1")
    const seen: BufferedEvent[] = []
    acp.subscribeToSession("C1")!.subscribe((entry) => { seen.push(entry) })
    children[0].kill()
    await settle()
    expect(seen).toEqual([])
  })
})

describe("session held by another process", () => {
  it("rejects with kiro-cli's lock error and leaves nothing registered", async () => {
    locked.add("K9")
    const error = await acp.openDeckSession("K9", "d9", "K9", "sdpm-orchestrator").catch((e: unknown) => e)
    const { sessionConflict } = await import("./sessionErrors")
    expect(sessionConflict(error)?.code).toBe("session_locked")
    expect(acp.hasProcess("K9")).toBe(false)
    expect(children[0].killed).toBe(true)
  })
})

describe("steer", () => {
  /** The steer states and the turn's end ("end", or "error" for a failed turn), in order. */
  const steerEvents = (seen: BufferedEvent[]) => seen
    .filter((e) => steerOf(e) || isEnd(e))
    .map((e) => steerOf(e)?.state ?? (payloadOf(e)?.status === "error" ? "error" : "end"))
  const steers = (seen: BufferedEvent[]) => seen.map(steerOf).filter(Boolean)

  async function running() {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "count to sixty")
    const seen: BufferedEvent[] = []
    prompted.subscribe((entry) => { seen.push(entry) })
    prompted.send()
    await settle()
    return { child: children[0], seen }
  }

  it("queues the message into the running turn and reports it delivered once V2 injects it (matched by text)", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "stop counting")
    expect(child.requests.find((r) => r.method === "_session/steer")?.params).toEqual({ sessionId: "K1", message: "stop counting" })
    expect(seen.at(-1)?.event).toEqual({ kind: "data", payload: { steer: { id: "m1", text: "stop counting", state: "accepted" } } })

    child.send({ method: "_kiro.dev/session/update", params: { sessionId: "K1", update: { sessionUpdate: "AgentExecutionSteeringInjected", messageId: "steer-abc", content: "stop counting" } } })
    await settle()
    expect(seen.at(-1)?.event).toEqual({ kind: "data", payload: { steer: { id: "m1", state: "delivered" } } })

    child.endTurn()
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "delivered", "end"])
    expect(child.requests.some((r) => r.method === "_session/steer/clear")).toBe(false)
    // Buffered for a /stream reconnect.
    expect(acp.getBufferedEvents("C1").filter(steerOf)).toHaveLength(2)
  })

  it("matches an injection by messageId before its text", async () => {
    const { child, seen } = await running()
    child.steerAnswer = { queued: true, messageId: "steer-9" }
    await acp.steerSession("C1", "m1", "first")
    child.steerAnswer = { queued: true, messageId: "steer-10" }
    await acp.steerSession("C1", "m2", "first")
    child.send({ method: "_kiro.dev/session/update", params: { sessionId: "K1", update: { sessionUpdate: "AgentExecutionSteeringInjected", messageId: "steer-10", content: "first" } } })
    await settle()
    expect(seen.at(-1)?.event).toMatchObject({ payload: { steer: { id: "m2", state: "delivered" } } })
  })

  it("refuses a message when no turn runs, and one kiro-cli does not queue", async () => {
    await acp.createNewProcessFor("C1")
    await expect(acp.steerSession("C1", "m1", "hi")).rejects.toMatchObject({ code: "session_idle" })
    await expect(acp.steerSession("nobody", "m1", "hi")).rejects.toMatchObject({ code: "session_idle" })

    const prompted = await acp.sendPrompt("C1", "count")
    const seen: BufferedEvent[] = []
    prompted.subscribe((entry) => { seen.push(entry) })
    prompted.send()
    await settle()
    children[0].steerAnswer = { queued: false, messageId: "steer-1", dropped: "epoch_changed" }
    await expect(acp.steerSession("C1", "m2", "late")).rejects.toMatchObject({ code: "steer_not_queued", message: expect.stringContaining("epoch_changed") })
    children[0].failing.add("_session/steer")
    await expect(acp.steerSession("C1", "m3", "broken")).rejects.toMatchObject({ code: "steer_not_queued", message: expect.stringContaining("_session/steer failed") })
    expect(steers(seen)).toEqual([])
  })

  it("on Stop, reports an unread message discarded at once, before the turn end, and clears it before the next prompt", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "remember KUMQUAT")
    child.silent.add("_session/steer/clear")
    acp.cancelSession("C1")
    child.endTurn("cancelled")
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "discarded", "end"])
    const clear = child.requests.find((r) => r.method === "_session/steer/clear")
    expect(clear?.params).toEqual({ sessionId: "K1" })

    // The next prompt waits until kiro-cli has emptied its queue.
    let next = false
    void acp.sendPrompt("C1", "next").then(() => { next = true })
    await settle()
    expect(next).toBe(false)
    child.send({ id: clear!.id, result: { cleared: true } })
    await settle()
    expect(next).toBe(true)
  })

  it("takes a message back out when the turn ends while kiro-cli queues it", async () => {
    const { child, seen } = await running()
    child.silent.add("_session/steer")
    const steered = acp.steerSession("C1", "m1", "too late")
    await settle()
    child.endTurn()
    await settle()
    const steer = child.requests.find((r) => r.method === "_session/steer")!
    child.send({ id: steer.id, result: { queued: true } })
    await expect(steered).rejects.toMatchObject({ code: "session_idle" })
    expect(child.requests.at(-1)?.method).toBe("_session/steer/clear")
    expect(steers(seen)).toEqual([])
  })

  it("continues a turn that ended before kiro-cli read a message with a follow-up prompt on the same stream", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "add a summary slide")
    await acp.steerSession("C1", "m2", "and use blue")
    child.endTurn()
    await settle()
    const methods = child.requests.map((r) => r.method)
    expect(methods.slice(-2)).toEqual(["_session/steer/clear", "session/prompt"])
    expect(child.requests.at(-1)?.params).toEqual({ sessionId: "K1", prompt: [{ type: "text", text: "add a summary slide\n\nand use blue" }] })
    expect(steerEvents(seen)).toEqual(["accepted", "accepted", "delivered", "delivered"])
    expect(acp.isSessionRunning("C1")).toBe(true)
    await expect(acp.sendPrompt("C1", "another")).rejects.toThrow(/still answering/)

    child.endTurn()
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "accepted", "delivered", "delivered", "end"])
    expect(acp.isSessionRunning("C1")).toBe(false)
  })

  it("ends the turn instead of continuing when Stop comes while the queue is cleared", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "more")
    child.silent.add("_session/steer/clear")
    child.endTurn()
    await settle()
    acp.cancelSession("C1")
    const clear = child.requests.find((r) => r.method === "_session/steer/clear")!
    child.send({ id: clear.id, result: { cleared: true } })
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "discarded", "end"])
    expect(seen.at(-1)?.event).toMatchObject({ kind: "end", stopReason: "cancelled" })
    expect(child.requests.filter((r) => r.method === "session/prompt")).toHaveLength(1)
  })

  it("leaves a message queued after the clear to kiro-cli, out of the follow-up prompt's text", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "first")
    child.silent.add("_session/steer/clear")
    child.endTurn()
    await settle()
    await acp.steerSession("C1", "m2", "second")
    const clear = child.requests.find((r) => r.method === "_session/steer/clear")!
    child.send({ id: clear.id, result: { cleared: true } })
    await settle()
    expect(child.requests.at(-1)?.params).toMatchObject({ prompt: [{ type: "text", text: "first" }] })
    // kiro-cli reads "second" in the follow-up prompt itself.
    child.send({ method: "_kiro.dev/session/update", params: { sessionId: "K1", update: { sessionUpdate: "AgentExecutionSteeringInjected", content: "second" } } })
    await settle()
    expect(steers(seen)).toMatchObject([
      { id: "m1", state: "accepted" }, { id: "m2", state: "accepted" }, { id: "m1", state: "delivered" }, { id: "m2", state: "delivered" },
    ])
  })

  it("reports an unread message discarded when kiro-cli exits, without a clear", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "hello")
    child.kill()
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "discarded", "error"])
    expect(child.requests.some((r) => r.method === "_session/steer/clear")).toBe(false)
  })
})

describe("chat events", () => {
  it("numbers a turn's events once: a listener and a reconnect see the same ids", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello")
    const live: number[] = []
    prompted.subscribe((entry) => { live.push(entry.id) })
    prompted.send()
    const child = children[0]
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "one" } })
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "two" } })
    await settle()
    child.endTurn()
    await settle()
    // work busy and turn (buffered before the listener came), two texts, turnEnd, work idle, end.
    expect(live).toEqual([3, 4, 5, 6, 7])
    expect(acp.getBufferedEvents("C1").map((e) => e.id)).toEqual([1, 2, ...live])
    expect(acp.getBufferedEvents("C1", 2).map((e) => e.id)).toEqual(live)
  })

  it("buffers the turn's notice as its first payload after the turn event", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello", { notice: "context_not_carried_over" })
    expect(acp.getBufferedEvents("C1").map((e) => e.event)).toEqual([
      { kind: "data", payload: { work: { state: "busy" } } },
      { kind: "data", payload: { turn: { id: expect.any(String), why: "prompt", text: "hello" } } },
      { kind: "data", payload: { notice: { code: "context_not_carried_over" } } },
    ])
    prompted.send()
    children[0].update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "hi" } })
    await settle()
    expect(acp.getBufferedEvents("C1").map((e) => e.id)).toEqual([1, 2, 3, 4])
  })

  it("keeps a sub-agent session's text and tool chunks out of the chat", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello")
    prompted.send()
    const child = children[0]
    child.update("S1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "composer says" } })
    child.send({ method: "_kiro.dev/session/update", params: { sessionId: "S1", update: { sessionUpdate: "tool_call_chunk", toolCallId: "s1-t", title: "list_templates" } } })
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "main says" } })
    await settle()
    expect(acp.getBufferedEvents("C1").map((e) => e.event).filter((e) => !("work" in e.payload! || "turn" in e.payload!))).toEqual([
      { kind: "data", payload: { event: { contentBlockDelta: { delta: { text: "main says" } } } } },
    ])
  })

  it.each(["end_turn", "max_tokens", "refusal", "cancelled", "an error"])("closes a Compose card still open when the turn ends with %s, its running group failed, before the end event", async (how) => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "compose")
    prompted.send()
    const child = children[0]
    child.update("K1", {
      sessionUpdate: "tool_call", toolCallId: "crew", title: "Spawning agent crew",
      rawInput: { stages: [{ name: "g1", prompt_template: "assigned_slugs: intro" }] }, _meta: { kiro: { toolName: "subagent" } },
    })
    await settle()
    if (how === "cancelled") acp.cancelSession("C1")
    if (how === "an error") child.failPrompt()
    else child.endTurn(how)
    await settle()
    const events = acp.getBufferedEvents("C1").map((e) => e.event)
    const card = { toolUseId: "crew", name: "compose_slides" }
    expect(events.slice(-5, -3).map((e) => e.payload)).toEqual([
      { toolStream: { ...card, data: { group: 1, slugs: "intro", status: "error" } } },
      { toolResult: { ...card, status: "error", content: "{}" } },
    ])
    expect(events.slice(-3, -1).map((e) => Object.keys(e.payload ?? {})[0])).toEqual(["turnEnd", "work"])
    expect(events.at(-1)?.kind).toBe("end")
  })
})

describe("steer without kiro-cli support", () => {
  it("stops sending steers to a process that answered Method not found, with one warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      await acp.createNewProcessFor("C1")
      const prompted = await acp.sendPrompt("C1", "count")
      prompted.send()
      await settle()
      const child = children[0]
      child.silent.add("_session/steer")
      const first = acp.steerSession("C1", "m1", "hi").catch((e: unknown) => e)
      await settle()
      const steer = child.requests.find((r) => r.method === "_session/steer")!
      child.send({ id: steer.id, error: { code: -32601, message: "Method not found: _session/steer" } })
      expect(await first).toMatchObject({ code: "steer_not_queued" })
      expect(await acp.steerSession("C1", "m2", "again").catch((e: unknown) => e)).toMatchObject({ code: "steer_not_queued" })
      expect(child.requests.filter((r) => r.method === "_session/steer")).toHaveLength(1)
      expect(warn.mock.calls.filter((call) => String(call[0]).includes("_session/steer"))).toHaveLength(1)
    } finally {
      warn.mockRestore()
    }
  })
})

/** A readable name for each event: the payload's key (and state), `end` for the end. */
function kinds(events: BufferedEvent[]): string[] {
  return events.map(({ event }) => {
    if (event.kind === "end") return "end"
    const payload = event.payload as Record<string, Record<string, unknown>>
    const key = Object.keys(payload)[0]
    if (key === "work") return `work ${payload.work.state}`
    if (key === "steer") return `steer ${payload.steer.state}`
    if (key === "event") return "contentBlockDelta" in payload.event ? "text" : "messageStart"
    return key
  })
}
const turnOf = (e: BufferedEvent) => payloadOf(e)?.turn as { id: string; why: string; text: string } | undefined
const textOfEvents = (events: BufferedEvent[]) => events
  .map((e) => ((payloadOf(e)?.event as { contentBlockDelta?: { delta: { text: string } } } | undefined)?.contentBlockDelta?.delta.text) ?? "")
  .join("")
const prompts = (child: FakeChild) => child.requests.filter((r) => r.method === "session/prompt").map((r) => (r.params.prompt as { text: string }[])[0].text)
const say = (child: FakeChild, sessionId: string, text: string) => child.update(sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text } })

/** A fake work hold (web-2's compose task). */
function fakeHold() {
  return { cancel: vi.fn(), dropped: vi.fn() }
}

/** C1's chat with a turn running ("build"), its listener's events in `seen`. */
async function runningTurn() {
  const { chat } = await acp.createNewProcessFor("C1")
  const prompted = await acp.sendPrompt("C1", "build", { displayText: "build" })
  const seen: BufferedEvent[] = []
  prompted.subscribe((entry) => { seen.push(entry) })
  prompted.send()
  await settle()
  return { chat, seen, child: children[0], prompted }
}

describe("work period", () => {
  it("runs work busy, turn, output, turnEnd, work idle and end, numbered from 1", async () => {
    const { child } = await runningTurn()
    say(child, "K1", "done")
    await settle()
    child.endTurn()
    await settle()
    const events = acp.getBufferedEvents("C1")
    expect(kinds(events)).toEqual(["work busy", "turn", "text", "turnEnd", "work idle", "end"])
    expect(events.map((e) => e.id)).toEqual([1, 2, 3, 4, 5, 6])
    expect(turnOf(events[1])).toEqual({ id: expect.any(String), why: "prompt", text: "build" })
    expect(payloadOf(events[3])).toEqual({ turnEnd: { id: turnOf(events[1])!.id, how: "finished" } })
    expect(payloadOf(events[4])).toEqual({ work: { state: "idle", how: "finished" } })

    // The next period is numbered from 1 again.
    const next = await acp.sendPrompt("C1", "again")
    expect(next.replayFrom).toBe(1)
    expect(acp.getBufferedEvents("C1").map((e) => e.id)).toEqual([1, 2])
  })

  it("keeps a turn continued with a steer as one turn", async () => {
    const { child } = await runningTurn()
    await acp.steerSession("C1", "m1", "also blue")
    child.endTurn()
    await settle()
    child.endTurn()
    await settle()
    expect(kinds(acp.getBufferedEvents("C1"))).toEqual(["work busy", "turn", "steer accepted", "steer delivered", "turnEnd", "work idle", "end"])
  })

  it("stays busy while work holds it after the turn, and ends when the hold releases", async () => {
    const { chat, child } = await runningTurn()
    const release = chat.hold(fakeHold())
    child.endTurn()
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(true)
    expect(kinds(acp.getBufferedEvents("C1"))).toEqual(["work busy", "turn", "turnEnd"])
    release()
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(kinds(acp.getBufferedEvents("C1")).slice(-2)).toEqual(["work idle", "end"])
    expect(() => chat.hold(fakeHold())).toThrow(/no work period/)
  })

  it("starts a prompt sent while work holds the period as a turn in it: replayed from that turn, after a messageStart", async () => {
    const { chat, child } = await runningTurn()
    say(child, "K1", "first answer")
    await settle()
    chat.hold(fakeHold())
    child.endTurn()
    await settle()

    const second = await acp.sendPrompt("C1", "second", { displayText: "second" })
    const replay = acp.getBufferedEvents("C1", second.replayFrom - 1)
    expect(second.replayFrom).toBe(5)
    expect(turnOf(replay[0])).toMatchObject({ why: "prompt", text: "second" })
    second.send()
    say(child, "K1", "second answer")
    await settle()
    const fromTurn = acp.getBufferedEvents("C1", second.replayFrom - 1)
    expect(kinds(fromTurn)).toEqual(["turn", "messageStart", "text"])
    expect(textOfEvents(fromTurn)).toBe("second answer")
    expect(prompts(child)).toEqual(["build", "second"])
  })

  it("starts a turn with a steer sent while work holds the period without a turn", async () => {
    const { chat, child } = await runningTurn()
    chat.hold(fakeHold())
    child.endTurn()
    await settle()
    await acp.steerSession("C1", "m1", "make it blue")
    await settle()
    const events = acp.getBufferedEvents("C1")
    expect(kinds(events).slice(3)).toEqual(["steer accepted", "turn", "steer delivered"])
    expect(turnOf(events[4])).toMatchObject({ why: "steer", text: "make it blue" })
    expect(prompts(child)).toEqual(["build", "make it blue"])
    expect(acp.isSessionRunning("C1")).toBe(true)
  })

  it("shows a turn's error at once when work holds the period, and not again with the period's end", async () => {
    const { chat, child } = await runningTurn()
    const release = chat.hold(fakeHold())
    child.failPrompt()
    await settle()
    const events = acp.getBufferedEvents("C1")
    expect(kinds(events)).toEqual(["work busy", "turn", "turnEnd", "status"])
    release()
    expect(acp.getBufferedEvents("C1").at(-1)?.event).toEqual({ kind: "end" })
    expect(payloadOf(acp.getBufferedEvents("C1").at(-2)!)).toEqual({ work: { state: "idle", how: "error" } })
  })
})

describe("deliver", () => {
  it("steers the Local server's text into a running turn, hidden: no steer event, none when kiro-cli reads it", async () => {
    const { chat, child, seen } = await runningTurn()
    chat.deliver("<compose_result/>", "wake")
    await settle()
    expect(child.requests.find((r) => r.method === "_session/steer")?.params).toEqual({ sessionId: "K1", message: "<compose_result/>" })
    child.send({ method: "_kiro.dev/session/update", params: { sessionId: "K1", update: { sessionUpdate: "AgentExecutionSteeringInjected", content: "<compose_result/>" } } })
    await settle()
    child.endTurn()
    await settle()
    expect(seen.filter(steerOf)).toEqual([])
    expect(prompts(child)).toEqual(["build"])
  })

  it("sends the text as the turn's follow-up prompt when kiro-cli does not implement steering", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const { chat, child } = await runningTurn()
      child.silent.add("_session/steer")
      chat.deliver("<compose_result/>", "wake")
      await settle()
      const steer = child.requests.find((r) => r.method === "_session/steer")!
      child.send({ id: steer.id, error: { code: -32601, message: "Method not found" } })
      await settle()
      child.endTurn()
      await settle()
      expect(prompts(child)).toEqual(["build", "<compose_result/>"])
      expect(kinds(acp.getBufferedEvents("C1")).filter((k) => k.startsWith("turn"))).toEqual(["turn"])
    } finally {
      warn.mockRestore()
    }
  })

  it("runs a hidden turn when work holds the period without a turn: no user text in the stream", async () => {
    const { chat, child } = await runningTurn()
    chat.hold(fakeHold())
    child.endTurn()
    await settle()
    chat.deliver("<compose_result task=\"1\"/>", "wake")
    await settle()
    const turns = acp.getBufferedEvents("C1").map(turnOf).filter(Boolean)
    expect(turns.at(-1)).toEqual({ id: expect.any(String), why: "wake", text: "" })
    expect(prompts(child)).toEqual(["build", "<compose_result task=\"1\"/>"])
    expect(JSON.stringify(acp.getBufferedEvents("C1"))).not.toContain("compose_result")
  })

  it("keeps the text for the next user prompt after Stop, and without a period; it goes in once", async () => {
    const { chat, child } = await runningTurn()
    acp.cancelSession("C1")
    chat.deliver("kept after Stop", "wake")
    child.endTurn("cancelled")
    await settle()
    chat.deliver("kept without a period", "report")
    expect(child.requests.filter((r) => r.method === "_session/steer")).toEqual([])

    const next = await acp.sendPrompt("C1", "hello", { displayText: "hello" })
    next.send()
    await settle()
    expect(prompts(child).at(-1)).toBe("kept after Stop\n\nkept without a period\n\nhello")
    expect(turnOf(acp.getBufferedEvents("C1")[1])?.text).toBe("hello")
    child.endTurn()
    await settle()
    const after = await acp.sendPrompt("C1", "plain")
    after.send()
    await settle()
    expect(prompts(child).at(-1)).toBe("plain")
  })
})

describe("Stop", () => {
  it("cancels the turn and every hold, sends nothing that starts model work afterwards, and drops a hold that does not release in 5 s", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const { chat, child, seen } = await runningTurn()
      const hold = fakeHold()
      chat.hold(hold)
      const order: string[] = []
      hold.dropped.mockImplementation(() => { order.push("dropped") })
      chat.subscribe((entry) => { order.push(kinds([entry])[0]) })
      const sentBefore = child.requests.length
      acp.cancelSession("C1")
      expect(child.cancelled).toEqual(["K1"])
      expect(hold.cancel).toHaveBeenCalledOnce()
      expect(chat.maySend()).toBe(false)

      // After Stop: the turn's answer, a text for the agent, a prompt, a steer.
      child.endTurn("cancelled")
      await settle()
      chat.deliver("late", "wake")
      await expect(acp.sendPrompt("C1", "now")).rejects.toMatchObject({ name: "SessionBusyError" })
      await expect(acp.steerSession("C1", "m1", "now")).rejects.toMatchObject({ code: "session_idle" })
      expect(acp.isSessionRunning("C1")).toBe(true)

      await vi.advanceTimersByTimeAsync(5000)
      expect(order).toEqual(["turnEnd", "dropped", "work idle", "end"])
      expect(seen.at(-1)?.event).toEqual({ kind: "end", stopReason: "cancelled" })
      expect(payloadOf(seen.at(-2)!)).toEqual({ work: { state: "idle", how: "cancelled" } })
      expect(child.requests.slice(sentBefore).filter((r) => r.method === "session/prompt" || r.method === "_session/steer")).toEqual([])
      expect(acp.isSessionRunning("C1")).toBe(false)
    } finally {
      warn.mockRestore()
      vi.useRealTimers()
    }
  })

  it("ends the period at once when the holds release after Stop", async () => {
    const { chat, child } = await runningTurn()
    const hold = fakeHold()
    const release = chat.hold(hold)
    hold.cancel.mockImplementation(() => release())
    acp.cancelSession("C1")
    child.endTurn("cancelled")
    await settle()
    expect(hold.dropped).not.toHaveBeenCalled()
    expect(acp.getBufferedEvents("C1").at(-1)?.event).toEqual({ kind: "end", stopReason: "cancelled" })
  })

  it("discards the user's steers and keeps the Local server's for the next prompt", async () => {
    const { chat, child, seen } = await runningTurn()
    await acp.steerSession("C1", "m1", "user words")
    chat.deliver("harness words", "wake")
    await settle()
    acp.cancelSession("C1")
    child.endTurn("cancelled")
    await settle()
    expect(seen.filter(steerOf).map(steerOf)).toEqual([
      { id: "m1", text: "user words", state: "accepted" }, { id: "m1", state: "discarded" },
    ])
    await settle()
    const next = await acp.sendPrompt("C1", "next")
    next.send()
    await settle()
    expect(prompts(child).at(-1)).toBe("harness words\n\nnext")
  })
})

describe("a kiro-cli that exits", () => {
  it("ends the running turn with agent_exited, and the chat's next message opens its session again", async () => {
    const { seen } = await runningTurn()
    children[0].kill()
    await settle()
    expect(seen.at(-1)?.event).toMatchObject({ kind: "end", payload: { code: "agent_exited" } })
    expect(acp.hasProcess("C1")).toBe(false)

    const reopened = await acp.createNewProcessFor("C1")
    expect(reopened).toMatchObject({ resumed: true })
    expect(reopened.chat.sessionId).toBe("K1")
    expect(children[1].requests.map((r) => r.method)).toEqual(["initialize", "session/new", "session/load"])
    expect(children[1].requests[2].params).toMatchObject({ sessionId: "K1" })
  })

  it("starts over with the notice when kiro-cli no longer has the session", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      await acp.createNewProcessFor("C1")
      children[0].kill()
      await settle()
      spawn.mockImplementationOnce((_command: string, args: string[]) => {
        const child = new FakeChild("K2", locked, args)
        child.missing.add("K1")
        children.push(child)
        return child
      })
      const reopened = await acp.createNewProcessFor("C1")
      expect(reopened).toMatchObject({ resumed: false, notice: "context_not_carried_over" })
      expect(reopened.chat.sessionId).toBe("K2")
    } finally {
      warn.mockRestore()
    }
  })
})
