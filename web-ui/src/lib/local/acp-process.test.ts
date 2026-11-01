// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The process map: a new chat's process is reachable under the client id (C) and its kiro
 * session id (K, what the deck's `.session` stores); close and eviction drop every key of a
 * process; the size limit counts processes, not keys; a prompt to a session still answering
 * is refused. kiro-cli is replaced by a fake child that answers the ACP requests.
 */

import { EventEmitter } from "events"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn() }))
vi.mock("./acp-adapter", () => ({
  getActiveAgent: () => ({ id: "kiro", path: "kiro-cli", args: ["acp", "--agent", "sdpm-orchestrator"], env: {} }),
}))

type Rpc = { id: number; method: string; params: Record<string, unknown> }

class FakeChild extends EventEmitter {
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin = { write: (line: string) => { this.handle(JSON.parse(line)); return true } }
  killed = false
  prompts: number[] = []
  constructor(private readonly sessionId: string, private readonly lockedSessions: Set<string>) { super() }

  private send(msg: Record<string, unknown>) {
    // Answer after rpcRequestTo has registered the pending request.
    setImmediate(() => this.stdout.emit("data", JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n"))
  }

  private handle(req: Rpc) {
    if (req.id == null) return
    if (req.method === "session/new") this.send({ id: req.id, result: { sessionId: this.sessionId } })
    else if (req.method === "session/load" && this.lockedSessions.has(req.params.sessionId as string)) {
      this.send({ id: req.id, error: { message: "Internal error", data: "Failed to start session: Session is active in another process (PID 1)" } })
    } else if (req.method === "session/prompt") this.prompts.push(req.id)
    else this.send({ id: req.id, result: {} })
  }

  endTurn() {
    this.send({ id: this.prompts.shift(), result: { stopReason: "end_turn" } })
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
