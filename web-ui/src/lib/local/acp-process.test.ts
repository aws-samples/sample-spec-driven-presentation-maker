// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The process map: a new chat's process is reachable under the client id (C) and its kiro
 * session id (K, what the deck's `.session` stores); close and eviction drop every key of a
 * process; the size limit counts processes, not keys; a prompt to a session still answering
 * is refused; a turn ends with the answer to its session/prompt (result or error), whatever the
 * sub-agent sessions or other requests sent, or with agent_exited when kiro-cli exits first;
 * kiro-cli's own requests are answered (permissions by option kind, the rest with Method not
 * found) and never taken for answers; setup requests time out and follow the caller's abort;
 * a steer goes into the running turn and is reported accepted, delivered (V2 by its text, V3 by
 * its messageId, or sent as a follow-up prompt when the prompt ended before kiro-cli read it) or
 * discarded when Stop or an exit ends the turn first; either way kiro-cli's queue is cleared.
 * kiro-cli is replaced by a fake child that answers the ACP requests.
 */

import { EventEmitter } from "events"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { STEER_EVENT } from "./steer"
import { TURN_END, TURN_ERROR } from "./turnErrors"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn() }))
vi.mock("./acp-adapter", () => ({
  getActiveAgent: () => ({ id: "kiro", path: "kiro-cli", args: ["acp", "--agent", "sdpm-orchestrator"], env: {} }),
}))

type Rpc = { id: number; method: string; params: Record<string, unknown> }

class FakeChild extends EventEmitter {
  pid = 4242
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin = Object.assign(new EventEmitter(), { write: (line: string) => { this.handle(JSON.parse(line)); return true } })
  killed = false
  prompts: number[] = []
  cancelled: string[] = []
  /** What this client wrote back for kiro-cli's own requests. */
  answers: Record<string, unknown>[] = []
  /** Methods answered with a JSON-RPC error instead of a result. */
  failing = new Set<string>()
  /** Methods never answered (a kiro-cli that hangs). */
  silent = new Set<string>()
  /** Every request this client sent, in order. */
  requests: Rpc[] = []
  /** The answer to `_session/steer` (V2 shape; V3 adds a messageId). */
  steerAnswer: Record<string, unknown> = { queued: true }
  constructor(private readonly sessionId: string, private readonly lockedSessions: Set<string>) { super() }

  send(msg: Record<string, unknown>) {
    // Answer after rpcRequestTo has registered the pending request.
    setImmediate(() => this.stdout.emit("data", JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n"))
  }

  private handle(req: Rpc) {
    if (req.method === undefined) { this.answers.push(req as unknown as Record<string, unknown>); return }
    if (req.method === "session/cancel") this.cancelled.push(req.params.sessionId as string)
    if (req.id == null) return
    this.requests.push(req)
    if (this.silent.has(req.method)) return
    if (req.method === "_session/steer" && !this.failing.has(req.method)) { this.send({ id: req.id, result: this.steerAnswer }); return }
    if (req.method === "session/new") this.send({ id: req.id, result: { sessionId: this.sessionId } })
    else if (req.method === "session/load" && this.lockedSessions.has(req.params.sessionId as string)) {
      this.send({ id: req.id, error: { message: "Internal error", data: "Failed to start session: Session is active in another process (PID 1)" } })
    } else if (req.method === "session/load") {
      // kiro-cli replays the loaded session's history under its id before answering.
      this.update(req.params.sessionId as string, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "earlier" } })
      this.send({ id: req.id, result: {} })
    } else if (req.method === "session/prompt") this.prompts.push(req.id)
    else if (this.failing.has(req.method)) this.send({ id: req.id, error: { message: "Internal error", data: `${req.method} failed` } })
    else this.send({ id: req.id, result: {} })
  }

  update(sessionId: string, update: Record<string, unknown>) {
    this.send({ method: "session/update", params: { sessionId, update } })
  }

  /** What kiro-cli 2.37 sends for a use_subagent call: sub-session updates and list_update, no turn_end. */
  runSubagent(subSessionId: string) {
    this.send({ method: "_kiro.dev/subagent/list_update", params: { subagents: [{ sessionId: subSessionId, status: { type: "working" } }] } })
    this.update(subSessionId, { sessionUpdate: "tool_call", toolCallId: `${subSessionId}-t`, title: "Running: @sdpm/generate_pptx" })
    this.update(subSessionId, { sessionUpdate: "tool_call_update", toolCallId: `${subSessionId}-t`, status: "completed" })
    this.send({ method: "_kiro.dev/subagent/list_update", params: { subagents: [{ sessionId: subSessionId, status: { type: "terminated" } }] } })
    this.send({ method: "_kiro.dev/subagent/list_update", params: { subagents: [] } })
  }

  endTurn(stopReason = "end_turn") {
    this.send({ id: this.prompts.shift(), result: { stopReason } })
  }

  failPrompt() {
    this.send({ id: this.prompts.shift(), error: { message: "Internal error", data: "model stream failed" } })
  }

  kill() {
    if (!this.killed) {
      this.killed = true
      setImmediate(() => this.emit("close", null))
    }
    return true
  }
}

const tick = () => new Promise((r) => setImmediate(r))
const settle = async () => { for (let i = 0; i < 10; i++) await tick() }

let children: FakeChild[]
let locked: Set<string>
let acp: typeof import("./acp-process")

beforeEach(async () => {
  children = []
  locked = new Set()
  spawn.mockReset()
  spawn.mockImplementation(() => {
    const child = new FakeChild(`K${children.length + 1}`, locked)
    children.push(child)
    return child
  })
  vi.resetModules()
  acp = await import("./acp-process")
})

afterEach(() => {
  for (const child of children) child.kill()
})

describe("process map", () => {
  it("registers a new chat's process under the client id and its kiro session id", async () => {
    const ps = await acp.createNewProcessFor("C1")
    expect(ps.sessionId).toBe("K1")
    expect(acp.hasProcess("C1")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(true)

    // Reopening the deck sends with K: the live process is reused, no second kiro-cli.
    expect(await acp.getOrCreateProcess("K1")).toBe(ps)
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
    await acp.getOrCreateProcess("K9")
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

  it("cancel reaches the main session and this turn's sub-agents, and ends the turn", async () => {
    await acp.createNewProcessFor("C1")
    const child = children[0]
    await turn(child, "C1", ["S1"])

    const prompted = await acp.sendPrompt("C1", "again")
    prompted.send()
    child.runSubagent("S2")
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
    const ends: Record<string, unknown>[] = []
    prompted.subscribe((msg) => { if (msg.method === TURN_ERROR || msg.method === TURN_END) ends.push(msg) })
    prompted.send()
    child.runSubagent("S1")
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(true)

    child.failPrompt()
    await settle()
    expect(ends).toEqual([{ method: TURN_ERROR, params: { sessionId: "K1", message: "Internal error: model stream failed" } }])
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
    child.failing.add("session/set_config_option")
    const prompted = await acp.sendPrompt("C1", "build the deck")
    const ends: Record<string, unknown>[] = []
    prompted.subscribe((msg) => { if (msg.method === TURN_ERROR || msg.method === TURN_END) ends.push(msg) })
    prompted.send()
    await settle()

    await expect(acp.setConfigOption("C1", "model", "unknown")).rejects.toThrow(/session\/set_config_option failed/)
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(true)
    expect(ends).toEqual([])
    await expect(acp.sendPrompt("C1", "again")).rejects.toThrow(/still answering/)

    child.endTurn()
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(ends).toEqual([{ method: TURN_END, params: { sessionId: "K1", stopReason: "end_turn" } }])
  })

  it.each(["end_turn", "cancelled", "refusal", "max_tokens", "max_turn_requests"])("ends the turn with stopReason %s and buffers the end for reconnects", async (stopReason) => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "build the deck")
    prompted.send()
    await settle()
    children[0].endTurn(stopReason)
    await settle()
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(acp.getBufferedEvents("C1").at(-1)?.msg).toEqual({ method: TURN_END, params: { sessionId: "K1", stopReason } })
  })

  it("ends a running turn with agent_exited when kiro-cli exits, and forgets the process", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "build the deck")
    const seen: Record<string, unknown>[] = []
    prompted.subscribe((msg) => { seen.push(msg) })
    prompted.send()
    await settle()

    children[0].kill()
    await settle()
    expect(seen.at(-1)).toMatchObject({ method: TURN_ERROR, params: { sessionId: "K1", code: "agent_exited" } })
    expect(acp.isSessionRunning("C1")).toBe(false)
    expect(acp.hasProcess("C1")).toBe(false)
    expect(acp.hasProcess("K1")).toBe(false)
  })

  it("sends no turn event when an idle process exits", async () => {
    await acp.createNewProcessFor("C1")
    const seen: Record<string, unknown>[] = []
    acp.subscribeToSession("C1")!.subscribe((msg) => { seen.push(msg) })
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
    const ends: Record<string, unknown>[] = []
    prompted.subscribe((msg) => { if (msg.method === TURN_ERROR || msg.method === TURN_END) ends.push(msg) })
    prompted.send()
    await settle()
    return { child, ends, promptId: child.prompts[0] }
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
    spawn.mockImplementationOnce(() => {
      const child = new FakeChild("K1", locked)
      child.silent.add("session/load")
      children.push(child)
      return child
    })
    const controller = new AbortController()
    const pending = acp.getOrCreateProcess("K9", "sdpm-orchestrator", { signal: controller.signal }).catch((e: unknown) => e)
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
    const error = await acp.getOrCreateProcess("K9").catch((e: unknown) => e)
    const { sessionConflict } = await import("./sessionErrors")
    expect(sessionConflict(error)?.code).toBe("session_locked")
    expect(acp.hasProcess("K9")).toBe(false)
    expect(children[0].killed).toBe(true)
  })
})

describe("steer", () => {
  const steerEvents = (seen: Record<string, unknown>[]) => seen
    .filter((m) => m.method === STEER_EVENT || m.method === TURN_END || m.method === TURN_ERROR)
    .map((m) => m.method === STEER_EVENT ? (m.params as { state: string }).state : m.method)

  async function running() {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "count to sixty")
    const seen: Record<string, unknown>[] = []
    prompted.subscribe((msg) => { seen.push(msg) })
    prompted.send()
    await settle()
    return { child: children[0], seen }
  }

  it("queues the message into the running turn and reports it delivered once V2 injects it (matched by text)", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "stop counting")
    expect(child.requests.find((r) => r.method === "_session/steer")?.params).toEqual({ sessionId: "K1", message: "stop counting" })
    expect(seen.at(-1)).toEqual({ method: STEER_EVENT, params: { sessionId: "K1", id: "m1", text: "stop counting", state: "accepted" } })

    child.send({ method: "_kiro.dev/session/update", params: { sessionId: "K1", update: { sessionUpdate: "AgentExecutionSteeringInjected", messageId: "steer-abc", content: "stop counting" } } })
    await settle()
    expect(seen.at(-1)).toEqual({ method: STEER_EVENT, params: { sessionId: "K1", id: "m1", state: "delivered" } })

    child.endTurn()
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "delivered", TURN_END])
    expect(child.requests.some((r) => r.method === "_session/steer/clear")).toBe(false)
    // Buffered for a /stream reconnect.
    expect(acp.getBufferedEvents("C1").filter((e) => e.msg.method === STEER_EVENT)).toHaveLength(2)
  })

  it("matches V3's steering_injected by messageId", async () => {
    const { child, seen } = await running()
    child.steerAnswer = { queued: true, messageId: "steer-9" }
    await acp.steerSession("C1", "m1", "first")
    child.steerAnswer = { queued: true, messageId: "steer-10" }
    await acp.steerSession("C1", "m2", "first")
    child.update("K1", { sessionUpdate: "session_info_update", _meta: { kiro: { kind: "steering_injected", messageId: "steer-10", content: "first" } } })
    await settle()
    expect(seen.at(-1)).toMatchObject({ method: STEER_EVENT, params: { id: "m2", state: "delivered" } })
  })

  it("refuses a message when no turn runs, and one kiro-cli does not queue", async () => {
    await acp.createNewProcessFor("C1")
    await expect(acp.steerSession("C1", "m1", "hi")).rejects.toMatchObject({ code: "session_idle" })
    await expect(acp.steerSession("nobody", "m1", "hi")).rejects.toMatchObject({ code: "session_idle" })

    const prompted = await acp.sendPrompt("C1", "count")
    const seen: Record<string, unknown>[] = []
    prompted.subscribe((msg) => { seen.push(msg) })
    prompted.send()
    await settle()
    children[0].steerAnswer = { queued: false, messageId: "steer-1", dropped: "epoch_changed" }
    await expect(acp.steerSession("C1", "m2", "late")).rejects.toMatchObject({ code: "steer_not_queued", message: expect.stringContaining("epoch_changed") })
    children[0].failing.add("_session/steer")
    await expect(acp.steerSession("C1", "m3", "broken")).rejects.toMatchObject({ code: "steer_not_queued", message: expect.stringContaining("_session/steer failed") })
    expect(seen.filter((m) => m.method === STEER_EVENT)).toEqual([])
  })

  it("on Stop, reports an unread message discarded before the turn end and clears it before the next prompt", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "remember KUMQUAT")
    acp.cancelSession("C1")
    child.silent.add("_session/steer/clear")
    child.endTurn("cancelled")
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "discarded", TURN_END])
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
    expect(seen.filter((m) => m.method === STEER_EVENT)).toEqual([])
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
    expect(steerEvents(seen)).toEqual(["accepted", "accepted", "delivered", "delivered", TURN_END])
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
    expect(steerEvents(seen)).toEqual(["accepted", "discarded", TURN_END])
    expect(seen.at(-1)).toMatchObject({ params: { stopReason: "cancelled" } })
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
    expect(seen.filter((m) => m.method === STEER_EVENT).map((m) => m.params)).toMatchObject([
      { id: "m1", state: "accepted" }, { id: "m2", state: "accepted" }, { id: "m1", state: "delivered" }, { id: "m2", state: "delivered" },
    ])
  })

  it("reports an unread message discarded when kiro-cli exits, without a clear", async () => {
    const { child, seen } = await running()
    await acp.steerSession("C1", "m1", "hello")
    child.kill()
    await settle()
    expect(steerEvents(seen)).toEqual(["accepted", "discarded", TURN_ERROR])
    expect(child.requests.some((r) => r.method === "_session/steer/clear")).toBe(false)
  })
})
