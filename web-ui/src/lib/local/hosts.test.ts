// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The host pool: every chat gets a kiro-cli of its own, on V3 and V2 (kiro-cli's V3 agent server
 * runs one turn at a time per process); a composer session joins its chat's kiro-cli; each line
 * reaches only its own session's sink, and its MCP state is recorded once per line, also before a
 * session knows its id (V2); a V2 session of another agent is switched to its mode; the cap
 * releases the least recently active idle chat and never a busy one; a start its chat gave up is
 * killed, an open given up next to another session ends that session after kiro-cli answered; a
 * listing's kiro-cli carries the chat environment and is killed when the listing is done; a host
 * exit reaches every sink; a steer kiro-cli does not implement is refused once and never sent again.
 * kiro-cli is replaced by the fake child (src/test/fakeKiro.ts).
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { LocalEvent } from "./conversation/events"
import type { HostSession, SessionSink } from "./hosts"
import { FakeChild, settle, tick } from "../../test/fakeKiro"
import { installFakeProcesses } from "../../test/fakeProcesses"

const { spawn, execFile, execFileSync } = vi.hoisted(() => ({ spawn: vi.fn(), execFile: vi.fn(), execFileSync: vi.fn() }))
vi.mock("child_process", () => ({ spawn, execFile, execFileSync, default: { spawn, execFile, execFileSync } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn(() => "d0") }))

let children: FakeChild[]
let hosts: typeof import("./hosts")
let sync: ReturnType<typeof vi.fn>
let configDir: string
/** Set up the next spawned child before it answers anything. */
let nextSetup: ((child: FakeChild) => void) | null

/** A recording sink, released the way the registry releases a chat. */
class Sink implements SessionSink {
  events: LocalEvent[] = []
  exits: (number | null)[] = []
  isBusy = false
  at = 0
  released = 0
  hs: HostSession | null = null
  constructor(readonly kind: "chat" | "aux" = "chat") {}
  onEvents(events: LocalEvent[]) { this.events.push(...events) }
  onHostExit(code: number | null) { this.exits.push(code) }
  busy() { return this.isBusy }
  lastActivity() { return this.at }
  release() {
    this.released++
    this.hs!.drop()
  }
  texts() { return this.events.flatMap((e) => (e.type === "text" ? [e.text] : [])) }
}

beforeEach(async () => {
  children = []
  nextSetup = null
  spawn.mockReset()
  installFakeProcesses({ spawn, execFile, execFileSync })
  spawn.mockImplementation((_command: string, args: string[]) => {
    const child = new FakeChild(`K${children.length + 1}`, new Set(), args)
    nextSetup?.(child)
    nextSetup = null
    children.push(child)
    return child
  })
  configDir = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-hosts-config-")) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", configDir)
  vi.resetModules()
  hosts = await import("./hosts")
  sync = vi.mocked((await import("./agents-sync")).syncToAgentsDir) as unknown as ReturnType<typeof vi.fn>
  sync.mockReset()
  sync.mockReturnValue("d0")
})

afterEach(() => {
  for (const child of children) child.kill()
  vi.useRealTimers()
  vi.unstubAllEnvs()
  fs.rmSync(configDir, { recursive: true, force: true })
})

/** Place a chat (or an aux session) on a host of `engine` and open a new session for it. */
async function open(engine: "v2" | "v3", sink: Sink = new Sink(), agentName = "sdpm-orchestrator") {
  const host = await hosts.pool.acquireForChat(engine, agentName)
  const { hs } = await host.openSession(agentName, { kind: "new" }, { sink })
  sink.hs = hs
  return { host, hs, sink }
}

describe("placement", () => {
  it.each(["v3", "v2"] as const)("gives each %s chat its own kiro-cli", async (engine) => {
    const a = await open(engine)
    const b = await open(engine)
    expect(spawn).toHaveBeenCalledTimes(2)
    expect(a.host).not.toBe(b.host)
    expect([a.hs.sessionId, b.hs.sessionId]).toEqual(["K1", "K2"])
    expect(a.host.canClose()).toBe(engine === "v3")
  })
})

describe("routing", () => {
  it("hands the session's lines to its sink, and records each MCP line once", async () => {
    const a = await open("v3")
    const apply = vi.spyOn(a.host.mcp, "apply")
    const child = children[0]
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "to A" } })
    child.update("K9", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "not A's" } })
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: " again" } })
    child.send({ method: "_kiro/mcp/status", params: { sessionId: "K1", servers: [{ name: "sdpm", status: "connected" }] } })
    await settle()
    expect(a.sink.texts()).toEqual(["to A", " again"])
    expect(apply.mock.calls.map((call) => call[0])).toEqual([
      { type: "mcp_snapshot", sessionId: "K1" },
      { type: "mcp_status", sessionId: "K1", server: "sdpm", state: "connected" },
    ])
    expect(a.sink.events.some((e) => e.type === "mcp_status" || e.type === "mcp_snapshot")).toBe(false)
  })

  it("refuses a second session on a kiro-cli", async () => {
    const a = await open("v3")
    await expect(a.host.openSession("sdpm-composer", { kind: "new" }, { sink: new Sink("aux") })).rejects.toThrow("host already carries a session")
    expect(children[0].requests.filter((r) => r.method === "session/new")).toHaveLength(1)
  })

  it("V2: counts server_initialized sent before the session/new answer, without waiting for the MCP timeout", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
    // The fake sends server_initialized ahead of the answer; no timer has to fire.
    const { hs } = await open("v2")
    expect(hs.sessionId).toBe("K1")
  })

  it("fails an open at once with agent_start_failed when kiro-cli exits while the session waits for the sdpm server", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const host = await hosts.pool.acquireForChat("v3", "sdpm-orchestrator")
    const child = children[0]
    child.mcpState = "none"
    const pending = host.openSession("sdpm-orchestrator", { kind: "new" }, { sink: new Sink() }).catch((e: unknown) => e)
    await settle()
    expect(child.requests.map((r) => r.method)).toContain("session/new")
    child.exit(3)
    expect(await pending).toMatchObject({ code: "agent_start_failed", message: "kiro-cli exited while starting (code 3)" })
    warn.mockRestore()
  })
})

describe("cap", () => {
  it.each(["v3", "v2"] as const)("kills the least recently active idle %s kiro-cli for a fourth chat, never a busy one", async (engine) => {
    const sinks = [new Sink(), new Sink(), new Sink()]
    sinks.forEach((sink, i) => { sink.at = 100 + i })
    for (const sink of sinks) await open(engine, sink)
    sinks[0].isBusy = true
    await open(engine)
    expect(children.map((c) => c.killed)).toEqual([false, true, false, false])
    expect(sinks.map((s) => s.released)).toEqual([0, 1, 0])
  })

  it("goes over the cap with a warning when every chat is busy", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      for (let i = 0; i < 3; i++) {
        const sink = new Sink()
        sink.isBusy = true
        await open("v3", sink)
      }
      await open("v3")
      expect(children.map((c) => c.killed)).toEqual([false, false, false, false])
      expect(warn.mock.calls.filter((call) => String(call[0]).includes("all busy"))).toHaveLength(1)
    } finally {
      warn.mockRestore()
    }
  })

  it("does not count a listing's kiro-cli, which has no chat", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      nextSetup = null
      await hosts.pool.acquireForListing("v2")
      for (let i = 0; i < 3; i++) await open("v2")
      expect(children.slice(1).map((c) => c.killed)).toEqual([false, false, false])
    } finally {
      log.mockRestore()
    }
  })
})

describe("aborts", () => {
  it.each(["v3", "v2"] as const)("kills a cold %s start when its chat gives up", async (engine) => {
    nextSetup = (child) => { child.silent.add("initialize") }
    const controller = new AbortController()
    const pending = hosts.pool.acquireForChat(engine, "sdpm-orchestrator", { signal: controller.signal }).catch((e: unknown) => e)
    await tick()
    controller.abort()
    expect(await pending).toMatchObject({ name: "AbortError" })
    expect(children[0].killed).toBe(true)
  })

  it("kills the kiro-cli when the open of its only session is given up", async () => {
    const host = await hosts.pool.acquireForChat("v3", "sdpm-orchestrator")
    children[0].silent.add("session/new")
    const controller = new AbortController()
    const pending = host.openSession("sdpm-orchestrator", { kind: "new" }, { sink: new Sink(), signal: controller.signal }).catch((e: unknown) => e)
    await settle()
    controller.abort()
    expect(await pending).toMatchObject({ name: "AbortError" })
    expect(children[0].killed).toBe(true)
  })

})

describe("listings", () => {
  it.each(["v3", "v2"] as const)("starts a %s kiro-cli with the chat environment for a listing and kills it afterwards", async (engine) => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      const listing = await hosts.pool.acquireForListing(engine)
      expect(await listing.request("session/list", {})).toEqual({})
      const env = spawn.mock.calls[0][2].env as NodeJS.ProcessEnv
      expect(env.SDPM_DECK_ROOT).toBeTruthy()
      expect(env.SDPM_OUTPUT_DIR).toBe(env.SDPM_DECK_ROOT)
      expect(sync).toHaveBeenCalledTimes(1)
      listing.release()
      expect(children[0].killed).toBe(true)
    } finally {
      log.mockRestore()
    }
  })

  it("lists through a live kiro-cli of the engine without starting one", async () => {
    await open("v3")
    const listing = await hosts.pool.acquireForListing("v3")
    await listing.request("session/list", {})
    listing.release()
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(children[0].killed).toBe(false)
  })
})

describe("exit and steer", () => {
  it("tells the sink when the kiro-cli exits", async () => {
    const a = await open("v3")
    children[0].kill()
    await settle()
    expect(a.sink.exits).toEqual([null])
    expect(a.host.session).toBeNull()
    expect(hosts.pool.hostsOf("v3")).toEqual([])
  })

  it("refuses a steer kiro-cli does not implement, with one warning, and sends no further steer", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const { hs, host } = await open("v3")
      const child = children[0]
      child.silent.add("_session/steer")
      const first = hs.steer("hi")
      await settle()
      const request = child.requests.find((r) => r.method === "_session/steer")!
      child.send({ id: request.id, error: { code: -32601, message: "Method not found: _session/steer" } })
      expect(await first).toEqual({ queued: false, dropped: "not_implemented" })
      expect(host.caps?.steer).toBe(false)
      expect(await hs.steer("again")).toEqual({ queued: false, dropped: "not_implemented" })
      expect(child.requests.filter((r) => r.method === "_session/steer")).toHaveLength(1)
      expect(warn.mock.calls.filter((call) => String(call[0]).includes("_session/steer"))).toHaveLength(1)
    } finally {
      warn.mockRestore()
    }
  })
})
