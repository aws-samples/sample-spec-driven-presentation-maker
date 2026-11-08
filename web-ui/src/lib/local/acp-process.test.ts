// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The process map: a new chat's process is reachable under the client id (C) and its kiro
 * session id (K, what the deck's `.session` stores); close and eviction drop every key of a
 * process; the size limit counts processes, not keys; a deck's saved kiro session is restored (or
 * its live process reused) under the client's id too, and only ids the process holds are keys;
 * a start that fails (another mode, a failed sdpm server, no sign-in, an early exit) registers
 * nothing; the configured engine starts kiro-cli (V3 without acp-config.json), and an engine switch ends the idle deck
 * processes of the other engine (a running one at the end of its turn); a deck's
 * `.session-engine` tells when its session also ran on the other engine; a prompt to a session still answering
 * is refused; a turn ends with the answer to its session/prompt (result or error), whatever the
 * sub-agent sessions or other requests sent, or with agent_exited when kiro-cli exits first;
 * kiro-cli's own requests are answered (permissions by option kind, the rest with Method not
 * found) and never taken for answers; setup requests time out and follow the caller's abort;
 * a steer goes into the running turn and is reported accepted, delivered (V2 by its text, V3 by
 * its messageId, or sent as a follow-up prompt when the prompt ended before kiro-cli read it) or
 * discarded when Stop or an exit ends the turn first; either way kiro-cli's queue is cleared.
 * The turn's chat events are numbered once, here, and a stream and a reconnect see the same
 * numbers; a turn's notice is its first event. A deck a tool result names gets the session's
 * `.session` (and a fork's origin) once, with or without a listener; a forgotten process drops
 * its pending origin. A fork cancelled once it exists is deleted before its kiro-cli is killed;
 * listing the stored sessions uses a live process of the engine, else a short-lived kiro-cli.
 * A chat's model and effort change at once on an idle live session (V3
 * set_config_option, V2 set_model), or are held and sent right before the next session/prompt;
 * a choice outside the offered models and levels is refused; the reported list is kept in
 * acp-models.json and listed without a process; V3 spawns leave the composer's model out.
 * kiro-cli is replaced by a fake child that answers the ACP requests.
 */

import { EventEmitter } from "events"
import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { BufferedEvent } from "./conversation/events"
import type { SessionOrigin } from "./kiro-sessions.types"
import { FAKE_MODELS, FakeChild, settle, tick } from "../../test/fakeKiro"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn() }))

const isEnd = (e: BufferedEvent) => e.event.kind === "end"
const payloadOf = (e: BufferedEvent) => e.event.payload as Record<string, unknown> | undefined
const steerOf = (e: BufferedEvent) => payloadOf(e)?.steer as { id: string; text?: string; state: string } | undefined

let children: FakeChild[]
let locked: Set<string>
let acp: typeof import("./acp-process")
let deckRoot: string
let configDir: string

beforeEach(async () => {
  deckRoot = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-acp-process-"))) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_DECK_ROOT", deckRoot)
  children = []
  locked = new Set()
  spawn.mockReset()
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

describe("process map", () => {
  it("registers a new chat's process under the client id and its kiro session id", async () => {
    const ps = await acp.createNewProcessFor("C1")
    expect(ps.sessionId).toBe("K1")
    expect(acp.hasProcess("C1")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(true)

    // Reopening the deck sends with K: the live process is reused, no second kiro-cli.
    expect((await acp.openDeckSession("K1", "d1", "K1", "sdpm-orchestrator")).ps).toBe(ps)
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("drops every key when the process closes", async () => {
    await acp.createNewProcessFor("C1")
    children[0].kill()
    await tick()
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.hasProcess("K1")).toBe(false)
  })

  it("counts processes, not keys, against the limit and evicts every key of the oldest", async () => {
    for (const id of ["C1", "C2", "C3"]) await acp.createNewProcessFor(id)
    expect(children.map((c) => c.killed)).toEqual([false, false, false])

    await acp.createNewProcessFor("C4")
    expect(children.map((c) => c.killed)).toEqual([true, false, false, false])
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.hasProcess("K1")).toBe(false)
    for (const id of ["C2", "K2", "C3", "K3", "C4", "K4"]) expect(acp.hasProcess(id)).toBe(true)
  })

  it("terminateProcess drops both keys", async () => {
    await acp.createNewProcessFor("C1")
    acp.terminateProcess("K1")
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.hasProcess("K1")).toBe(false)
    expect(children[0].killed).toBe(true)
  })

  it("restores a deck's saved kiro session under the client's own id as well", async () => {
    const { ps, outcome } = await acp.openDeckSession("D0", "d0", "K9", "sdpm-orchestrator")
    expect(outcome).toBe("resumed")
    expect(ps.sessionId).toBe("K9")
    expect(acp.hasProcess("D0")).toBe(true)
    expect(acp.hasProcess("K9")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(false)
    expect((await acp.openDeckSession("D0", "d0", "K9", "sdpm-orchestrator")).ps).toBe(ps)
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("reuses the live process of the saved kiro session for another client id, which then sends without a spawn", async () => {
    const ps = await acp.createNewProcessFor("C1")
    const opened = await acp.openDeckSession("D0", "d0", "K1", "sdpm-orchestrator")
    expect(opened).toMatchObject({ ps, outcome: "resumed" })
    expect(ps.deckBound).toBe(true)
    expect([...ps.savedDecks]).toEqual(["d0"])
    const prompted = await acp.sendPrompt("D0", "hello")
    expect(prompted.sessionId).toBe("K1")
    expect(spawn).toHaveBeenCalledTimes(1)

    acp.terminateProcess("D0")
    for (const id of ["C1", "D0", "K1"]) expect(acp.hasProcess(id)).toBe(false)
  })

  it("keys a V2 session kiro-cli no longer has by the new session only", async () => {
    spawn.mockImplementationOnce((_command: string, args: string[]) => {
      const child = new FakeChild("K1", locked, args)
      child.missing.add("OLD")
      children.push(child)
      return child
    })
    const { ps, outcome } = await acp.openDeckSession("D0", "d0", "OLD", "sdpm-orchestrator")
    expect(outcome).toBe("created")
    expect(ps.sessionId).toBe("K1")
    expect(acp.hasProcess("D0")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(true)
    expect(acp.hasProcess("OLD")).toBe(false)
    // Another tab opens the deck by its new .session: the same process.
    expect((await acp.openDeckSession("D1", "d0", "K1", "sdpm-orchestrator")).ps).toBe(ps)
    expect(spawn).toHaveBeenCalledTimes(1)
  })
})

describe("sendPrompt", () => {
  it("refuses a prompt while the session is still answering, from either key", async () => {
    await acp.createNewProcessFor("C1")
    const first = await acp.sendPrompt("C1", "hello")
    first.send()
    await tick()

    await expect(acp.sendPrompt("K1", "again")).rejects.toBeInstanceOf((await import("./sessionErrors")).SessionBusyError)
    await expect(acp.sendPrompt("C1", "again")).rejects.toThrow(/still answering/)

    children[0].endTurn()
    await tick()
    await tick()
    const next = await acp.sendPrompt("K1", "after the turn")
    expect(next.sessionId).toBe("K1")
    expect(spawn).toHaveBeenCalledTimes(1)
  })
})

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

describe("requests from kiro-cli", () => {
  async function promptRunning() {
    await acp.createNewProcessFor("C1")
    const child = children[0]
    const prompted = await acp.sendPrompt("C1", "build the deck")
    const ends: BufferedEvent[] = []
    prompted.subscribe((entry) => { if (isEnd(entry)) ends.push(entry) })
    prompted.send()
    await settle()
    return { child, ends, promptId: child.prompts[0].id }
  }

  it("does not take a request whose id equals the prompt's for the prompt's answer", async () => {
    const { child, ends, promptId } = await promptRunning()
    child.send({ id: promptId, method: "session/request_permission", params: { sessionId: "K1", options: [{ optionId: "allow_once", kind: "allow_once" }] } })
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(true)
    expect(ends).toEqual([])
    expect(child.answers).toEqual([{ jsonrpc: "2.0", id: promptId, result: { outcome: { outcome: "selected", optionId: "allow_once" } } }])

    child.endTurn()
    await settle()
    expect(ends).toHaveLength(1)
  })

  it.each([
    ["V2", [{ optionId: "allow_always", kind: "allow_always" }, { optionId: "allow_once", kind: "allow_once" }, { optionId: "reject_once", kind: "reject_once" }], "allow_once"],
    ["V3", [{ optionId: "accept", kind: "allow_once" }, { optionId: "always-accept", kind: "allow_always" }, { optionId: "reject", kind: "reject_once" }, { optionId: "always-reject", kind: "reject_always" }], "accept"],
    ["only always", [{ optionId: "trust", kind: "allow_always" }, { optionId: "no", kind: "reject_once" }], "trust"],
  ])("approves a permission request with the offered allow option (%s)", async (_engine, options, optionId) => {
    const { child } = await promptRunning()
    child.send({ id: 77, method: "session/request_permission", params: { sessionId: "K1", options } })
    await settle()
    expect(child.answers).toEqual([{ jsonrpc: "2.0", id: 77, result: { outcome: { outcome: "selected", optionId } } }])
  })

  it("answers a request it does not implement with Method not found", async () => {
    const { child, ends } = await promptRunning()
    child.send({ id: 5, method: "_kiro/openExternalUrl", params: { url: "https://kiro.dev" } })
    await settle()
    expect(child.answers).toEqual([{ jsonrpc: "2.0", id: 5, error: { code: -32601, message: "Method not found: _kiro/openExternalUrl" } }])
    expect(ends).toEqual([])
    expect(acp.isSessionRunning("C1")).toBe(true)
  })
})

describe("setup requests", () => {
  it("time out when kiro-cli does not answer, kill the process and register nothing", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
    try {
      spawn.mockImplementationOnce(() => {
        const child = new FakeChild("K1", locked)
        child.silent.add("initialize")
        children.push(child)
        return child
      })
      const pending = acp.createNewProcessFor("C1").catch((e: unknown) => e)
      await vi.advanceTimersByTimeAsync(30_000)
      const error = await pending
      const { AgentTimeoutError } = await import("./turnErrors")
      expect(error).toBeInstanceOf(AgentTimeoutError)
      expect((error as Error).message).toMatch(/initialize within 30s/)
      expect(children[0].killed).toBe(true)
      expect(acp.hasProcess("C1")).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it("stop when the caller's signal aborts", async () => {
    spawn.mockImplementationOnce((_command: string, args: string[]) => {
      const child = new FakeChild("K1", locked, args)
      child.silent.add("session/load")
      children.push(child)
      return child
    })
    const controller = new AbortController()
    const pending = acp.openDeckSession("K9", "d9", "K9", "sdpm-orchestrator", { signal: controller.signal }).catch((e: unknown) => e)
    await settle()
    controller.abort()
    const error = await pending
    expect((error as Error).name).toBe("AbortError")
    expect(children[0].killed).toBe(true)
    expect(acp.hasProcess("K9")).toBe(false)
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

  it("on Stop, reports an unread message discarded before the turn end and clears it before the next prompt", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "remember KUMQUAT")
    acp.cancelSession("C1")
    child.silent.add("_session/steer/clear")
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
    expect(live).toEqual([1, 2, 3])
    expect(acp.getBufferedEvents("C1").map((e) => e.id)).toEqual(live)
    expect(acp.getBufferedEvents("C1", 1).map((e) => e.id)).toEqual([2, 3])
  })

  it("buffers the turn's notice as its first event", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello", { notice: "context_not_carried_over" })
    expect(acp.getBufferedEvents("C1")).toEqual([{ id: 1, event: { kind: "data", payload: { notice: { code: "context_not_carried_over" } } } }])
    prompted.send()
    children[0].update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "hi" } })
    await settle()
    expect(acp.getBufferedEvents("C1").map((e) => e.id)).toEqual([1, 2])
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
    expect(acp.getBufferedEvents("C1").map((e) => e.event)).toEqual([{ kind: "data", payload: { event: { contentBlockDelta: { delta: { text: "main says" } } } } }])
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
    expect(events.slice(-3, -1).map((e) => e.payload)).toEqual([
      { toolStream: { ...card, data: { group: 1, slugs: "intro", status: "error" } } },
      { toolResult: { ...card, status: "error", content: "{}" } },
    ])
    expect(events.at(-1)?.kind).toBe("end")
  })
})

describe("deck detection", () => {
  const ORIGIN: SessionOrigin = { sourceSessionId: "SRC", title: "earlier chat", cwd: "/workspace", updatedAt: "2026-11-05T00:00:00.000Z", forkedAt: "2026-11-06T00:00:00.000Z" }
  const deckFile = (deckId: string, name: string) => path.join(deckRoot, deckId, name) // nosemgrep: path-join-resolve-traversal — constant deck ids in a tmpdir
  const readDeckFile = (deckId: string, name: string) => fs.existsSync(deckFile(deckId, name)) ? fs.readFileSync(deckFile(deckId, name), "utf-8") : null
  const makeDeck = (deckId: string) => fs.mkdirSync(path.join(deckRoot, deckId)) // nosemgrep: path-join-resolve-traversal — constant deck id in a tmpdir

  async function turnWith(results: Record<string, unknown>[]) {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "make a deck")
    prompted.send()
    results.forEach((result, i) => children[0].toolResult("K1", `t${i}`, result))
    await settle()
  }

  it("writes .session and the fork's origin with no listener, and drops the pending origin", async () => {
    makeDeck("d1")
    acp.pendingOrigins.set("C1", ORIGIN)
    await turnWith([{ output_dir: deckRoot }, { output_dir: path.join(deckRoot, "d1") }]) // nosemgrep: path-join-resolve-traversal — constant deck id in a tmpdir
    expect(readDeckFile("d1", ".session")).toBe("K1")
    expect(JSON.parse(readDeckFile("d1", ".session-origin.json")!)).toEqual(ORIGIN)
    expect(acp.pendingOrigins.has("C1")).toBe(false)
  })

  it("writes a deck's .session once, and a second deck's without the origin", async () => {
    makeDeck("d1")
    makeDeck("d2")
    acp.pendingOrigins.set("C1", ORIGIN)
    await turnWith([{ deckId: "d1" }])
    fs.writeFileSync(deckFile("d1", ".session"), "edited")
    children[0].toolResult("K1", "t9", { deckId: "d1" })
    children[0].toolResult("K1", "t10", { deckId: "d2" })
    await settle()
    expect(readDeckFile("d1", ".session")).toBe("edited")
    expect(readDeckFile("d2", ".session")).toBe("K1")
    expect(readDeckFile("d2", ".session-origin.json")).toBeNull()
  })

  it("shows the deck id it found in the tool result", async () => {
    makeDeck("d1")
    await turnWith([{ output_dir: path.join(deckRoot, "d1") }]) // nosemgrep: path-join-resolve-traversal — constant deck id in a tmpdir
    const result = acp.getBufferedEvents("C1").map(payloadOf).find((p) => p?.toolResult)?.toolResult as { content: string }
    expect(JSON.parse(result.content)).toEqual({ output_dir: path.join(deckRoot, "d1"), deckId: "d1" }) // nosemgrep: path-join-resolve-traversal — constant deck id in a tmpdir
  })

  it.each([
    ["exits", () => { children[0].kill() }],
    ["is terminated", () => { acp.terminateProcess("C1") }],
    ["is evicted", async () => { for (const id of ["C2", "C3", "C4"]) await acp.createNewProcessFor(id) }],
  ])("drops the pending origin when the process %s", async (_case, forget) => {
    await acp.createNewProcessFor("C1")
    acp.pendingOrigins.set("C1", ORIGIN)
    await forget()
    await settle()
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.pendingOrigins.has("C1")).toBe(false)
  })
})

describe("start-up failures", () => {
  /** The next kiro-cli, set up by `setup`. */
  function nextChild(setup: (child: FakeChild) => void) {
    spawn.mockImplementationOnce((_command: string, args: string[]) => {
      const child = new FakeChild("K1", locked, args)
      setup(child)
      children.push(child)
      return child
    })
  }

  it.each(["v2", "v3"] as const)("refuses a %s session that does not run the requested agent's mode, and registers nothing", async (engine) => {
    useEngine(engine)
    nextChild((child) => { child.newMode = engine === "v3" ? "vibe" : "kiro_default" })
    const pending = acp.createNewProcessFor("C1").catch((e: unknown) => e)
    // V2 / V3 say why right after the answer; the check waits for it.
    await settle()
    const notFound = engine === "v3" ? "_kiro/customAgent/not_found" : "_kiro.dev/agent/not_found"
    children[0].send({ method: notFound, params: { sessionId: "K1", requestedAgent: "sdpm-orchestrator", fallbackAgent: "vibe" } })
    expect(await pending).toMatchObject({ name: "AgentStartError", code: "agent_definition_rejected" })
    expect(children[0].killed).toBe(true)
    expect(acp.hasProcess("C1")).toBe(false)
  })

  it.each(["v2", "v3"] as const)("fails with mcp_failed when the %s sdpm server reports failed, and registers nothing", async (engine) => {
    useEngine(engine)
    nextChild((child) => { child.mcpState = "failed" })
    expect(await acp.createNewProcessFor("C1").catch((e: unknown) => e)).toMatchObject({ code: "mcp_failed" })
    expect(children[0].killed).toBe(true)
    expect(acp.hasProcess("C1")).toBe(false)
  })

  it("fails with agent_auth_required when kiro-cli answers -32000", async () => {
    nextChild((child) => { child.silent.add("session/new") })
    const pending = acp.createNewProcessFor("C1").catch((e: unknown) => e)
    await settle()
    const request = children[0].requests.find((r) => r.method === "session/new")!
    children[0].send({ id: request.id, error: { code: -32000, message: "Authentication required. Not logged in." } })
    expect(await pending).toMatchObject({ code: "agent_auth_required" })
    expect(acp.hasProcess("C1")).toBe(false)
  })

  it("fails with agent_start_failed when kiro-cli exits while starting, and logs its stderr", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    try {
      nextChild((child) => {
        child.silent.add("initialize")
        setImmediate(() => {
          child.stderr.emit("data", "error: unexpected argument '--agent-engine'\n")
          child.kill()
        })
      })
      expect(await acp.createNewProcessFor("C1").catch((e: unknown) => e)).toMatchObject({ code: "agent_start_failed" })
      expect(acp.hasProcess("C1")).toBe(false)
      expect(error.mock.calls.flat().join(" ")).toContain("unexpected argument '--agent-engine'")
    } finally {
      error.mockRestore()
    }
  })
})

describe("engines", () => {
  const makeDeck = (deckId: string) => fs.mkdirSync(path.join(deckRoot, deckId)) // nosemgrep: path-join-resolve-traversal — constant deck id in a tmpdir
  const deckFile = (deckId: string, name: string) => path.join(deckRoot, deckId, name) // nosemgrep: path-join-resolve-traversal — constant deck ids in a tmpdir
  const mark = (deckId: string) => JSON.parse(fs.readFileSync(deckFile(deckId, ".session-engine"), "utf-8"))

  async function turn(clientId: string, child: FakeChild) {
    const prompted = await acp.sendPrompt(clientId, "hello")
    prompted.send()
    await settle()
    child.endTurn()
    await settle()
  }

  it("starts kiro-cli with the configured engine's arguments after the configured command arguments", async () => {
    fs.writeFileSync(path.join(configDir, "acp-config.json"), JSON.stringify({ version: 2, engine: "v3", command: "/usr/bin/node", commandArgs: ["stub.mjs"] })) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
    await acp.createNewProcessFor("C1")
    expect(spawn.mock.calls[0].slice(0, 2)).toEqual(["/usr/bin/node", ["stub.mjs", "acp", "--agent-engine", "v3"]])
    useEngine("v2")
    await acp.createNewProcessFor("C2", "sdpm-style")
    expect(spawn.mock.calls[1].slice(0, 2)).toEqual(["kiro-cli", ["acp", "--agent", "sdpm-style"]])
  })

  it("starts kiro-cli on V3 when acp-config.json does not exist", async () => {
    fs.rmSync(path.join(configDir, "acp-config.json")) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
    await acp.createNewProcessFor("C1")
    expect(spawn.mock.calls[0].slice(0, 2)).toEqual(["kiro-cli", ["acp", "--agent-engine", "v3"]])
  })

  it("ends only the idle deck processes of another engine when the engine changes", async () => {
    makeDeck("d1")
    makeDeck("d2")
    const fresh = await acp.createNewProcessFor("C1")
    const reopened = (await acp.openDeckSession("C2", "d1", "K9", "sdpm-orchestrator")).ps
    const created = (await acp.openDeckSession("C3", "d2", null, "sdpm-orchestrator")).ps
    expect([fresh.deckBound, reopened.deckBound, created.deckBound]).toEqual([false, true, true])

    acp.terminateIdleProcesses("v2")
    expect(children.map((c) => c.killed)).toEqual([false, false, false])
    acp.terminateIdleProcesses("v3")
    expect(children.map((c) => c.killed)).toEqual([false, true, true])
    expect(acp.hasProcess("C1")).toBe(true)
    expect(["C2", "K9", "C3", "K3"].some((id) => acp.hasProcess(id))).toBe(false)
  })

  it("ends a deck process whose turn ran during the switch at the end of the turn, and keeps a chat without a deck", async () => {
    await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
    await acp.createNewProcessFor("C2")
    const deckTurn = await acp.sendPrompt("C1", "build")
    deckTurn.send()
    const chatTurn = await acp.sendPrompt("C2", "chat")
    chatTurn.send()
    await settle()
    useEngine("v3")
    acp.terminateIdleProcesses("v3")
    expect(children.map((c) => c.killed)).toEqual([false, false])

    children[0].endTurn()
    children[1].endTurn()
    await settle()
    expect(acp.getBufferedEvents("C2").at(-1)?.event).toMatchObject({ kind: "end", stopReason: "end_turn" })
    expect(children.map((c) => c.killed)).toEqual([true, false])
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.hasProcess("C2")).toBe(true)
  })

  it("opens a V3 session with session/load alone and its mode, and reports an empty one as created", async () => {
    useEngine("v3")
    makeDeck("d1")
    spawn.mockImplementationOnce((_command: string, args: string[]) => {
      const child = new FakeChild("unused", locked, args)
      child.missing.add("sess_gone")
      child.loadedMode = "sdpm-style"
      children.push(child)
      return child
    })
    const { ps, outcome } = await acp.openDeckSession("C1", "d1", "sess_gone", "sdpm-orchestrator")
    expect(outcome).toBe("created")
    expect(ps.sessionId).toBe("sess_gone")
    expect(children[0].requests.map((r) => r.method)).toEqual(["initialize", "session/load", "session/set_mode"])
    expect(children[0].requests[2].params).toEqual({ sessionId: "sess_gone", modeId: "sdpm-orchestrator" })
    expect(fs.readFileSync(deckFile("d1", ".session"), "utf-8")).toBe("sess_gone")
    expect(mark("d1")).toEqual({ version: 1, last: "v3", engines: ["v3"] })
  })

  it("marks the engines that ran a deck's turns, and reports the other engine's turns once each way", async () => {
    makeDeck("d1")
    fs.writeFileSync(deckFile("d1", ".session"), "K9")
    // An unmarked deck (all V2 so far) opened on V3: nothing is missing.
    useEngine("v3")
    let opened = await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
    expect(opened).toMatchObject({ outcome: "resumed", otherEngine: false })
    await turn("C1", children[0])
    expect(mark("d1")).toEqual({ version: 1, last: "v3", engines: ["v2", "v3"] })

    // Back on V2: the V3 turns are not in V2's copy.
    useEngine("v2")
    acp.terminateIdleProcesses("v2")
    opened = await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
    expect(opened).toMatchObject({ outcome: "resumed", otherEngine: true })
    await turn("C1", children[1])
    expect(mark("d1")).toEqual({ version: 1, last: "v2", engines: ["v2", "v3"] })

    // And on V3 again.
    useEngine("v3")
    acp.terminateIdleProcesses("v3")
    expect((await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")).otherEngine).toBe(true)
  })

  it("replaces the mark with the new session's engine when a deck's session is created", async () => {
    makeDeck("d1")
    fs.writeFileSync(deckFile("d1", ".session-engine"), JSON.stringify({ version: 1, last: "v3", engines: ["v2", "v3"] }))
    const opened = await acp.openDeckSession("C1", "d1", null, "sdpm-orchestrator")
    expect(opened).toMatchObject({ outcome: "created", otherEngine: false })
    expect(fs.readFileSync(deckFile("d1", ".session"), "utf-8")).toBe("K1")
    expect(mark("d1")).toEqual({ version: 1, last: "v2", engines: ["v2"] })
  })

  it("treats a broken mark as none, with one warning, and rewrites it at the next turn", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      makeDeck("d1")
      fs.writeFileSync(deckFile("d1", ".session-engine"), JSON.stringify({ version: 1, last: "v9", engines: ["v9"] }))
      useEngine("v3")
      expect((await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")).otherEngine).toBe(false)
      acp.readEngineMark("d1")
      expect(warn.mock.calls.filter((call) => String(call[1]) === "d1")).toHaveLength(1)
      await turn("C1", children[0])
      expect(mark("d1")).toEqual({ version: 1, last: "v3", engines: ["v2", "v3"] })
    } finally {
      warn.mockRestore()
    }
  })

  it("goes on with the turn when the mark cannot be written", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      makeDeck("d1")
      fs.mkdirSync(deckFile("d1", ".session-engine"))
      await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
      await turn("C1", children[0])
      expect(acp.getBufferedEvents("C1").at(-1)?.event).toMatchObject({ kind: "end", stopReason: "end_turn" })
      expect(warn.mock.calls.some((call) => String(call[0]).includes("could not write"))).toBe(true)
    } finally {
      warn.mockRestore()
    }
  })

  it("writes a new mark with the .session of a deck the turn creates", async () => {
    makeDeck("d1")
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "make a deck")
    prompted.send()
    children[0].update("K1", { sessionUpdate: "tool_call", toolCallId: "t1", title: "@sdpm/init_presentation", rawInput: { tool_id: "sdpm::init_presentation", arguments: {} }, _meta: { kiro: { serverName: "sdpm" } } })
    children[0].update("K1", { sessionUpdate: "tool_call_update", toolCallId: "t1", status: "completed", rawOutput: { response: JSON.stringify({ deckId: "d1" }) }, _meta: { kiro: { serverName: "sdpm" } } })
    await settle()
    expect(fs.readFileSync(deckFile("d1", ".session"), "utf-8")).toBe("K1")
    expect(mark("d1")).toEqual({ version: 1, last: "v3", engines: ["v3"] })
  })

  it("ignores a .session that does not hold a session id", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      makeDeck("d1")
      fs.writeFileSync(deckFile("d1", ".session"), "../../etc/passwd")
      expect(acp.readSessionFromDeck("d1")).toBeNull()
      fs.writeFileSync(deckFile("d1", ".session"), "sess_0d3c2b1a-1111-4111-8111-111111111111\n")
      expect(acp.readSessionFromDeck("d1")).toBe("sess_0d3c2b1a-1111-4111-8111-111111111111")
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })

  it("opens a fork's copy by the fork's id, and reports a copy kiro-cli could not read as created", async () => {
    useEngine("v3")
    spawn.mockImplementationOnce((_command: string, args: string[]) => {
      const child = new FakeChild("unused", locked, args)
      child.missing.add("F1")
      children.push(child)
      return child
    })
    const phases: string[] = []
    const { ps, outcome } = await acp.openForkedSession("F1", "sdpm-orchestrator", { onPhase: (phase) => { phases.push(phase) } })
    expect(outcome).toBe("created")
    expect(ps.sessionId).toBe("F1")
    expect(ps.deckBound).toBe(false)
    expect(phases[0]).toBe("starting")
    expect(await acp.openForkedSession("F1", "sdpm-orchestrator")).toMatchObject({ ps, outcome: "resumed" })
  })
})

describe("forks and listing", () => {
  it("forks on V3 and registers the fork under its id", async () => {
    useEngine("v3")
    const phases: string[] = []
    const { ps, sessionId, outcome } = await acp.forkSession("sess_src", "sdpm-orchestrator", { onPhase: (phase) => { phases.push(phase) } })
    expect({ sessionId, outcome }).toEqual({ sessionId: "F1", outcome: "resumed" })
    expect(ps.clientId).toBe("F1")
    expect([...new Set(phases)]).toEqual(["starting", "copying", "loading"])
    expect(children[0].requests.map((r) => r.method)).toEqual(["initialize", "session/fork", "session/load"])
    expect(acp.hasProcess("F1")).toBe(true)
  })

  it("deletes a fork cancelled during its load before killing its kiro-cli", async () => {
    useEngine("v3")
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      spawn.mockImplementationOnce((_command: string, args: string[]) => {
        const child = new FakeChild("unused", locked, args)
        child.silent.add("session/load")
        const kill = child.kill.bind(child)
        child.kill = () => { child.requests.push({ id: -1, method: "(killed)", params: {} }); return kill() }
        children.push(child)
        return child
      })
      const controller = new AbortController()
      const pending = acp.forkSession("sess_src", "sdpm-orchestrator", { signal: controller.signal }).catch((e: unknown) => e)
      await settle()
      expect(children[0].requests.map((r) => r.method)).toEqual(["initialize", "session/fork", "session/load"])
      controller.abort()
      expect(await pending).toMatchObject({ name: "AbortError" })
      expect(children[0].requests.map((r) => r.method).slice(3)).toEqual(["session/delete", "(killed)"])
      expect(children[0].requests[3].params).toEqual({ sessionId: "F1" })
      expect(acp.hasProcess("F1")).toBe(false)
    } finally {
      log.mockRestore()
    }
  })

  it("discards a live fork through its process, and leaves an id it did not fork alone", async () => {
    useEngine("v3")
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      await acp.createNewProcessFor("C1")
      await acp.discardForkedSession("K1")
      expect(children[0].requests.some((r) => r.method === "session/delete")).toBe(false)
      expect(warn).toHaveBeenCalled()
      await acp.forkSession("sess_src", "sdpm-orchestrator")
      await acp.discardForkedSession("F1")
      expect(children[1].requests.at(-1)).toMatchObject({ method: "session/delete", params: { sessionId: "F1" } })
      expect(children[1].killed).toBe(true)
      expect(acp.hasProcess("F1")).toBe(false)
    } finally {
      warn.mockRestore()
      log.mockRestore()
    }
  })

  it("lists through a live process of the engine without starting kiro-cli", async () => {
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    const answer = await acp.withEngineConnection("v3", async (connect) => (await connect()).request("session/list", {}))
    expect(answer).toEqual({})
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(children[0].requests.at(-1)?.method).toBe("session/list")
  })

  it("otherwise lists through a short-lived kiro-cli in servers/local that is killed afterwards, and none when not asked", async () => {
    useEngine("v2")
    await acp.createNewProcessFor("C1")
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      expect(await acp.withEngineConnection("v3", async () => "no connection")).toBe("no connection")
      expect(spawn).toHaveBeenCalledTimes(1)
      await acp.withEngineConnection("v3", async (connect) => (await connect()).request("session/list", {}))
      await settle()
      expect(spawn).toHaveBeenCalledTimes(2)
      expect(spawn.mock.calls[1][1]).toEqual(["acp", "--agent-engine", "v3"])
      expect(spawn.mock.calls[1][2]).toMatchObject({ cwd: expect.stringMatching(/servers[\\/]local$/) })
      expect(children[1].requests.map((r) => r.method)).toEqual(["initialize", "session/list"])
      expect(children[1].killed).toBe(true)
      expect(children[0].killed).toBe(false)
    } finally {
      log.mockRestore()
    }
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

describe("models", () => {
  const methods = (child: FakeChild) => child.requests.map((r) => r.method)
  const cacheFile = () => path.join(configDir, "acp-models.json") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir

  it("changes an idle V3 session's model and effort at once", async () => {
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    expect(acp.getSessionModels("C1")).toMatchObject({ engine: "v3", current: { model: "auto", effort: null, effortLevels: [] }, pending: null })
    expect(acp.getSessionModels("C1").available.map((m) => m.modelId)).toEqual(FAKE_MODELS)

    const view = await acp.chooseSessionModel("C1", { model: "m-effort", effort: "high" })
    expect(children[0].requests.filter((r) => r.method === "session/set_config_option").map((r) => r.params)).toEqual([
      { sessionId: "K1", configId: "model", value: "m-effort" },
      { sessionId: "K1", configId: "effortLevel", value: "high" },
    ])
    expect(view).toMatchObject({ current: { model: "m-effort", effort: "high", effortLevels: ["low", "high"] }, pending: null })
  })

  it("holds a choice made during a turn until the next prompt, and sends it first", async () => {
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    const child = children[0]
    const prompted = await acp.sendPrompt("C1", "build")
    prompted.send()
    await settle()
    expect(await acp.chooseSessionModel("C1", { model: "m-plain" })).toMatchObject({ current: { model: "auto" }, pending: { model: "m-plain" } })
    expect(methods(child)).not.toContain("session/set_config_option")
    child.endTurn()
    await settle()

    const next = await acp.sendPrompt("C1", "again")
    next.send()
    await settle()
    expect(methods(child).slice(-2)).toEqual(["session/set_config_option", "session/prompt"])
    expect(acp.getSessionModels("C1")).toMatchObject({ current: { model: "m-plain" }, pending: null })
  })

  it("keeps a new chat's choice until its process exists, and applies it before the first prompt", async () => {
    useEngine("v3")
    expect(await acp.chooseSessionModel("C0", {}).catch((e: unknown) => e)).toMatchObject({ code: "models_unknown" })
    await acp.createNewProcessFor("C1")
    acp.terminateProcess("C1")

    // The list the first process reported is known without a process.
    expect(await acp.chooseSessionModel("N1", { model: "m-effort" })).toMatchObject({ current: null, pending: { model: "m-effort" } })
    expect(await acp.chooseSessionModel("N1", { effort: "high" })).toMatchObject({ pending: { model: "m-effort", effort: "high" } })
    // A new model drops the effort chosen for the previous one.
    expect((await acp.chooseSessionModel("N1", { model: "m-plain" })).pending).toEqual({ model: "m-plain" })
    await acp.chooseSessionModel("N1", { model: "m-effort", effort: "low" })

    await acp.createNewProcessFor("N1")
    const child = children[1]
    expect(methods(child)).not.toContain("session/set_config_option")
    const prompted = await acp.sendPrompt("N1", "hello")
    prompted.send()
    await settle()
    expect(child.requests.filter((r) => r.method !== "initialize" && r.method !== "session/new").map((r) => [r.method, r.params.value])).toEqual([
      ["session/set_config_option", "m-effort"], ["session/set_config_option", "low"], ["session/prompt", undefined],
    ])
  })

  it("changes a V2 session's model with session/set_model and offers no effort", async () => {
    await acp.createNewProcessFor("C1")
    expect(acp.getSessionModels("C1")).toMatchObject({ engine: "v2", current: { model: "auto", effort: null } })
    expect(await acp.chooseSessionModel("C1", { model: "m-effort", effort: "low" }).catch((e: unknown) => e)).toMatchObject({ code: "effort_not_supported" })
    const view = await acp.chooseSessionModel("C1", { model: "m-plain" })
    expect(children[0].requests.find((r) => r.method === "session/set_model")?.params).toEqual({ sessionId: "K1", modelId: "m-plain" })
    expect(view.current?.model).toBe("m-plain")
  })

  it.each([
    ["unknown_model", { model: "no-such-model" }],
    ["effort_not_supported", { effort: "low" }],
    ["effort_not_supported", { model: "m-plain", effort: "low" }],
    ["unknown_effort", { model: "m-effort", effort: "max" }],
  ])("refuses %s (%j) and changes nothing", async (code, choice) => {
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    expect(await acp.chooseSessionModel("C1", choice).catch((e: unknown) => e)).toMatchObject({ name: "ModelChoiceError", code })
    expect(methods(children[0])).not.toContain("session/set_config_option")
    expect(acp.getSessionModels("C1").pending).toBeNull()
  })

  it("reports a change kiro-cli refuses and keeps nothing", async () => {
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    children[0].failing.add("session/set_config_option")
    expect(await acp.chooseSessionModel("C1", { model: "m-plain" }).catch((e: unknown) => e)).toMatchObject({ code: "model_not_changed" })
    expect(acp.getSessionModels("C1")).toMatchObject({ current: { model: "auto" }, pending: null })
  })

  it("warns and still prompts when the held choice cannot be applied", async () => {
    useEngine("v3")
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      await acp.createNewProcessFor("C1")
      const child = children[0]
      const first = await acp.sendPrompt("C1", "build")
      first.send()
      await settle()
      await acp.chooseSessionModel("C1", { model: "m-plain" })
      child.endTurn()
      await settle()
      child.failing.add("session/set_config_option")
      const next = await acp.sendPrompt("C1", "again")
      next.send()
      await settle()
      expect(methods(child).slice(-2)).toEqual(["session/set_config_option", "session/prompt"])
      expect(warn).toHaveBeenCalledWith("[acp] sessionId=%s: could not apply the chat's model choice: %s", "K1", expect.stringContaining("failed"))
      expect(acp.isSessionRunning("C1")).toBe(true)
    } finally {
      warn.mockRestore()
    }
  })

  it("writes the list a session reported to acp-models.json and reads it without a process", async () => {
    useEngine("v3")
    expect(acp.getSessionModels()).toEqual({ engine: "v3", available: [], current: null, pending: null })
    await acp.createNewProcessFor("C1")
    expect(JSON.parse(fs.readFileSync(cacheFile(), "utf-8")).engines.v3.map((m: { modelId: string }) => m.modelId)).toEqual(FAKE_MODELS)
    expect(JSON.parse(fs.readFileSync(cacheFile(), "utf-8")).engines.v3[1]).toEqual({ modelId: "m-effort", name: "M-EFFORT", effortLevels: ["low", "high"], defaultEffort: "low", rate: 2 })

    vi.resetModules()
    acp = await import("./acp-process")
    expect(acp.getSessionModels("C9")).toMatchObject({ engine: "v3", current: null })
    expect(acp.getSessionModels().available.map((m) => m.modelId)).toEqual(FAKE_MODELS)
    useEngine("v2")
    expect(acp.getSessionModels().available).toEqual([])
  })

  it("leaves the Settings model out of the composer's definition on V3 only", async () => {
    const { syncToAgentsDir } = await import("./agents-sync")
    useEngine("v3")
    await acp.createNewProcessFor("C1")
    useEngine("v2")
    await acp.createNewProcessFor("C2")
    expect(vi.mocked(syncToAgentsDir).mock.calls.map((call) => call[2])).toEqual([{ pinSubagentModel: false }, { pinSubagentModel: true }])
  })
})
