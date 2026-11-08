// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The ACP transport: an error answer keeps its JSON-RPC code and data; the answer's handler
 * runs before the request's promise settles; kiro-cli's permission requests are answered with
 * the offered allow_once option (V3's four options included) and logged; a request whose id
 * equals one of ours is answered, never taken for our answer; requests this client does not
 * implement get Method not found; an exit fails the requests still waiting, and the exit with the
 * end of stdout is an exit even while a child of kiro-cli holds its stderr. `detached` reaches
 * spawn (not on Windows); `SDPM_ACP_TRACE` gets every line written and read, with the pid.
 */

import { EventEmitter } from "events"
import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))

import { AcpRequestError, spawnAcp, type AcpConnection } from "./transport"

class FakeChild extends EventEmitter {
  pid = 4242
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin = Object.assign(new EventEmitter(), { write: (line: string) => { this.written.push(JSON.parse(line)); return true } })
  written: Record<string, unknown>[] = []
  send(msg: Record<string, unknown>) {
    this.stdout.emit("data", JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n")
  }
  kill() {
    setImmediate(() => this.emit("close", 1))
    return true
  }
}

let child: FakeChild
let conn: AcpConnection

beforeEach(() => {
  child = new FakeChild()
  spawn.mockReset()
  spawn.mockReturnValue(child)
  conn = spawnAcp("kiro-cli", ["acp"], { cwd: "/tmp", env: process.env })
})

afterEach(() => { vi.restoreAllMocks() })

const tick = () => new Promise((r) => setImmediate(r))

describe("requests", () => {
  it("rejects an error answer with AcpRequestError, keeping code and data", async () => {
    const pending = conn.request("session/load", { sessionId: "K1" })
    child.send({ id: 1, error: { code: -32000, message: "Internal error", data: "Session not found: K1" } })
    const error = await pending.catch((e: unknown) => e)
    expect(error).toBeInstanceOf(AcpRequestError)
    expect(error).toMatchObject({ code: -32000, data: "Session not found: K1", message: "Internal error: Session not found: K1" })
  })

  it("hands the answer to onAnswer before the promise settles", async () => {
    const order: string[] = []
    const { response } = conn.startRequest("session/prompt", {}, { onAnswer: (answer) => order.push(`answer ${answer.ok}`) })
    void response.then(() => order.push("resolved"))
    child.send({ id: 1, result: { stopReason: "end_turn" } })
    expect(order).toEqual(["answer true"])
    await tick()
    expect(order).toEqual(["answer true", "resolved"])
  })

  it("fails the waiting requests when the process exits", async () => {
    const pending = conn.request("session/prompt", {})
    const exits: (number | null)[] = []
    conn.onExit((code) => exits.push(code))
    child.kill()
    await expect(pending).rejects.toThrow(/exited with code 1/)
    expect(exits).toEqual([1])
    expect(conn.exited).toBe(true)
    await expect(conn.request("session/new", {})).rejects.toThrow(/has exited/)
  })

  it("calls it exited when kiro-cli exits and its stdout ends, while a child of its still holds stderr", async () => {
    const pending = conn.request("session/prompt", {})
    const exits: (number | null)[] = []
    conn.onExit((code) => exits.push(code))
    child.emit("exit", null)
    expect(exits).toEqual([])
    child.stdout.emit("close")
    await expect(pending).rejects.toThrow(/exited with code null/)
    expect(exits).toEqual([null])
    child.emit("close", null)
    expect(exits).toEqual([null])
  })

  it("passes notifications on in line order", () => {
    const seen: string[] = []
    conn.onNotification((msg) => seen.push(msg.method))
    child.stdout.emit("data", [
      JSON.stringify({ jsonrpc: "2.0", method: "session/update", params: {} }),
      JSON.stringify({ jsonrpc: "2.0", method: "_kiro.dev/metadata", params: {} }),
    ].join("\n") + "\n")
    expect(seen).toEqual(["session/update", "_kiro.dev/metadata"])
  })
})

describe("requests from kiro-cli", () => {
  it("answers V3's four-option permission request with its allow_once option, and logs it", () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    child.send({
      id: 7, method: "session/request_permission", params: {
        sessionId: "K1",
        toolCall: { toolCallId: "t1", kind: "read", title: "Read File" },
        options: [
          { optionId: "accept", name: "Accept", kind: "allow_once" },
          { optionId: "always-accept", name: "Always", kind: "allow_always" },
          { optionId: "reject", name: "Reject", kind: "reject_once" },
          { optionId: "always-reject", name: "Never", kind: "reject_always" },
        ],
      },
    })
    expect(child.written).toEqual([{ jsonrpc: "2.0", id: 7, result: { outcome: { outcome: "selected", optionId: "accept" } } }])
    expect(log).toHaveBeenCalledWith("[acp] pid %s permission %s \"%s\" → %s", 4242, "read", "Read File", "allow_once")
  })

  it("answers with allow_always when no allow_once is offered, and cancels when nothing fits", () => {
    vi.spyOn(console, "log").mockImplementation(() => {})
    child.send({ id: 8, method: "session/request_permission", params: { options: [{ optionId: "trust", kind: "allow_always" }, { optionId: "no", kind: "reject_once" }] } })
    child.send({ id: 9, method: "session/request_permission", params: { options: [] } })
    expect(child.written).toEqual([
      { jsonrpc: "2.0", id: 8, result: { outcome: { outcome: "selected", optionId: "trust" } } },
      { jsonrpc: "2.0", id: 9, result: { outcome: { outcome: "cancelled" } } },
    ])
  })

  it("does not take a request whose id equals ours for our answer", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {})
    let settled = false
    const { id, response } = conn.startRequest("session/prompt", {})
    void response.then(() => { settled = true })
    child.send({ id, method: "session/request_permission", params: { options: [{ optionId: "ok", kind: "allow_once" }] } })
    await tick()
    expect(settled).toBe(false)
    child.send({ id, result: { stopReason: "end_turn" } })
    await expect(response).resolves.toEqual({ stopReason: "end_turn" })
  })

  it("answers a request it does not implement with Method not found", () => {
    child.send({ id: 5, method: "_kiro/openExternalUrl", params: { url: "https://kiro.dev" } })
    expect(child.written).toEqual([{ jsonrpc: "2.0", id: 5, error: { code: -32601, message: "Method not found: _kiro/openExternalUrl" } }])
  })
})

describe("spawn options and the trace", () => {
  it("passes detached to spawn on macOS and Linux, and not on Windows", () => {
    spawnAcp("kiro-cli", ["acp"], { cwd: "/tmp", env: process.env, detached: true })
    expect(spawn.mock.calls.at(-1)![2]).toMatchObject({ detached: true })
    expect(spawn.mock.calls[0][2]).not.toHaveProperty("detached")
    const platform = Object.getOwnPropertyDescriptor(process, "platform")!
    Object.defineProperty(process, "platform", { value: "win32" })
    try {
      spawnAcp("kiro-cli", ["acp"], { cwd: "/tmp", env: process.env, detached: true })
    } finally {
      Object.defineProperty(process, "platform", platform)
    }
    expect(spawn.mock.calls.at(-1)![2]).not.toHaveProperty("detached")
    expect(conn.pid).toBe(4242)
  })

  it("writes one out and one in line with the pid to SDPM_ACP_TRACE", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "acp-trace-"))
    const file = path.join(dir, "trace.jsonl")
    vi.stubEnv("SDPM_ACP_TRACE", file)
    try {
      const pending = conn.request("initialize", { protocolVersion: 1 })
      child.send({ id: 1, result: { protocolVersion: 1 } })
      await pending
      const lines = fs.readFileSync(file, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
      expect(lines.map((l) => [l.pid, l.dir, l.msg.method ?? l.msg.result?.protocolVersion])).toEqual([[4242, "out", "initialize"], [4242, "in", 1]])
      expect(typeof lines[0].t).toBe("number")
    } finally {
      vi.unstubAllEnvs()
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })
})
