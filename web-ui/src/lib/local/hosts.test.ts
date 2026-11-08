// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The host pool: V3 chats share one kiro-cli (its initialize advertises session/close), V2 chats
 * get one each; each line reaches only its own session's sink, and its MCP state is recorded once
 * per line, also before a session knows its id (V2); a V2 session of another agent is switched to
 * its mode; the caps release the least recently active idle chat and never a busy one; a start
 * every waiting chat gave up is killed, a warm open given up ends its session after kiro-cli
 * answered; changed definitions retire a host; a listing's shared host stays for the next chat
 * and carries the chat environment, a V2 one is killed; a host exit reaches every sink; a steer
 * kiro-cli does not implement is refused once and never sent again.
 * kiro-cli is replaced by the fake child (src/test/fakeKiro.ts).
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { LocalEvent } from "./conversation/events"
import type { HostSession, SessionSink } from "./hosts"
import { FakeChild, settle, tick } from "../../test/fakeKiro"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))
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
    const hs = this.hs!
    void hs.close().catch(() => {})
    if (!hs.host.shared()) hs.host.kill()
  }
  texts() { return this.events.flatMap((e) => (e.type === "text" ? [e.text] : [])) }
}

beforeEach(async () => {
  children = []
  nextSetup = null
  spawn.mockReset()
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

/** The initialize answer a fake child of `engine` would give. */
function initializeAnswer(child: FakeChild) {
  const id = child.requests.find((r) => r.method === "initialize")!.id
  child.send({ id, result: { protocolVersion: 1, agentCapabilities: { sessionCapabilities: child.engine === "v3" ? { list: {}, close: {}, delete: {}, fork: {} } : {} } } })
}

describe("placement", () => {
  it("places two V3 chats on one kiro-cli, two sessions", async () => {
    const a = await open("v3")
    const b = await open("v3")
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(a.host).toBe(b.host)
    expect(a.host.shared()).toBe(true)
    expect([a.hs.sessionId, b.hs.sessionId]).toEqual(["K1", "K1-2"])
    expect(children[0].requests.filter((r) => r.method === "session/new")).toHaveLength(2)
  })

  it("gives each V2 chat its own kiro-cli", async () => {
    const a = await open("v2")
    const b = await open("v2")
    expect(spawn).toHaveBeenCalledTimes(2)
    expect(a.host).not.toBe(b.host)
    expect(a.host.shared()).toBe(false)
  })

  it("waits for a start of the engine and then places the chat on it when it is shared", async () => {
    const [a, b] = await Promise.all([open("v3"), open("v3")])
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(a.host).toBe(b.host)
  })
})

describe("routing", () => {
  it("hands each session's lines only to its own sink, and records each MCP line once", async () => {
    const a = await open("v3")
    const b = await open("v3")
    const apply = vi.spyOn(a.host.mcp, "apply")
    const child = children[0]
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "to A" } })
    child.update("K1-2", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "to B" } })
    child.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: " again" } })
    child.send({ method: "_kiro/mcp/status", params: { sessionId: "K1-2", servers: [{ name: "sdpm", status: "connected" }] } })
    await settle()
    expect(a.sink.texts()).toEqual(["to A", " again"])
    expect(b.sink.texts()).toEqual(["to B"])
    expect(apply.mock.calls.map((call) => call[0])).toEqual([
      { type: "mcp_snapshot", sessionId: "K1-2" },
      { type: "mcp_status", sessionId: "K1-2", server: "sdpm", state: "connected" },
    ])
    expect([...a.sink.events, ...b.sink.events].some((e) => e.type === "mcp_status" || e.type === "mcp_snapshot")).toBe(false)
  })

  it("V2: counts server_initialized sent before the session/new answer, without waiting for the MCP timeout", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
    const opened = open("v2")
    // The fake sends server_initialized ahead of the answer; no timer has to fire.
    const { hs } = await opened
    expect(hs.sessionId).toBe("K1")
  })

  it("V2: opens a composer session on the orchestrator's kiro-cli with set_mode", async () => {
    const chat = await open("v2")
    const aux = new Sink("aux")
    const { hs } = await chat.host.openSession("sdpm-composer", { kind: "new" }, { sink: aux })
    expect(hs.sessionId).toBe("K1-2")
    expect(children[0].requests.map((r) => r.method).slice(-2)).toEqual(["session/new", "session/set_mode"])
    expect(children[0].requests.at(-1)?.params).toEqual({ sessionId: "K1-2", modeId: "sdpm-composer" })
    expect(chat.host.auxOpened).toBe(1)
    expect(spawn).toHaveBeenCalledTimes(1)
  })
})

describe("caps", () => {
  it("releases the least recently active idle chat for the ninth on a V3 kiro-cli, never a busy one", async () => {
    const sinks: Sink[] = []
    for (let i = 0; i < 8; i++) {
      const sink = new Sink()
      sink.at = 100 + i
      sinks.push(sink)
      await open("v3", sink)
    }
    sinks[0].isBusy = true
    await open("v3")
    await settle()
    expect(sinks.map((s) => s.released)).toEqual([0, 1, 0, 0, 0, 0, 0, 0])
    expect(children[0].closed).toEqual(["K1-2"])
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("goes over the cap with one warning when every chat on the V3 kiro-cli is busy", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const sinks: Sink[] = []
      for (let i = 0; i < 8; i++) {
        const sink = new Sink()
        sink.isBusy = true
        sinks.push(sink)
        await open("v3", sink)
      }
      const ninth = new Sink()
      ninth.isBusy = true
      await open("v3", ninth)
      await open("v3")
      expect(sinks.every((s) => s.released === 0)).toBe(true)
      expect(children[0].closed).toEqual([])
      expect(warn.mock.calls.filter((call) => String(call[0]).includes("busy chats"))).toHaveLength(1)
    } finally {
      warn.mockRestore()
    }
  })

  it("kills the least recently active idle V2 kiro-cli for a fourth chat, never a busy one", async () => {
    const sinks = [new Sink(), new Sink(), new Sink()]
    sinks.forEach((sink, i) => { sink.at = 100 + i })
    for (const sink of sinks) await open("v2", sink)
    sinks[0].isBusy = true
    await open("v2")
    expect(children.map((c) => c.killed)).toEqual([false, true, false, false])
    expect(sinks.map((s) => s.released)).toEqual([0, 1, 0])
  })
})

describe("aborts", () => {
  it("kills a cold start when its only waiting chat gives up, and keeps one a second chat waits for", async () => {
    nextSetup = (child) => { child.silent.add("initialize") }
    const first = new AbortController()
    const pending = hosts.pool.acquireForChat("v3", "sdpm-orchestrator", { signal: first.signal }).catch((e: unknown) => e)
    await tick()
    const second = hosts.pool.acquireForChat("v3", "sdpm-orchestrator")
    await tick()
    first.abort()
    expect(await pending).toMatchObject({ name: "AbortError" })
    expect(children[0].killed).toBe(false)
    initializeAnswer(children[0])
    expect((await second).conn.pid).toBe(4242)
    expect(spawn).toHaveBeenCalledTimes(1)

    nextSetup = (child) => { child.silent.add("initialize") }
    const alone = new AbortController()
    const lonely = hosts.pool.acquireForChat("v2", "sdpm-orchestrator", { signal: alone.signal }).catch((e: unknown) => e)
    await tick()
    alone.abort()
    expect(await lonely).toMatchObject({ name: "AbortError" })
    expect(children[1].killed).toBe(true)
  })

  it("kills a cold V3 kiro-cli when the open of its only session is given up", async () => {
    const host = await hosts.pool.acquireForChat("v3", "sdpm-orchestrator")
    children[0].silent.add("session/new")
    const controller = new AbortController()
    const pending = host.openSession("sdpm-orchestrator", { kind: "new" }, { sink: new Sink(), signal: controller.signal }).catch((e: unknown) => e)
    await settle()
    controller.abort()
    expect(await pending).toMatchObject({ name: "AbortError" })
    expect(children[0].killed).toBe(true)
  })

  it("deletes a session opened on a warm V3 kiro-cli for a chat that gave up, once kiro-cli answered, and keeps the host", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      const other = await open("v3")
      const child = children[0]
      child.silent.add("session/new")
      const controller = new AbortController()
      const pending = other.host.openSession("sdpm-orchestrator", { kind: "new" }, { sink: new Sink(), signal: controller.signal }).catch((e: unknown) => e)
      await settle()
      controller.abort()
      await settle()
      expect(child.deleted).toEqual([])
      // kiro-cli answers the session/new the chat gave up.
      child.silent.delete("session/new")
      const request = child.requests.filter((r) => r.method === "session/new").at(-1)!
      child.send({ method: "_kiro/mcp/status", params: { sessionId: "K1-2", servers: [{ name: "sdpm", status: "connected" }] } })
      child.send({ id: request.id, result: { sessionId: "K1-2", modes: { currentModeId: "sdpm-orchestrator", availableModes: [] } } })
      expect(await pending).toMatchObject({ name: "AbortError" })
      await settle()
      expect(child.deleted).toEqual(["K1-2"])
      expect(child.killed).toBe(false)
      expect(other.host.sessions.size).toBe(1)
    } finally {
      log.mockRestore()
    }
  })
})

describe("definitions and listings", () => {
  it("retires a host whose agent definitions changed: the next chat gets a new kiro-cli, and the old idle one ends at that start", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      const first = await open("v3")
      sync.mockReturnValue("d1")
      const second = await open("v3")
      expect(spawn).toHaveBeenCalledTimes(2)
      expect(second.host).not.toBe(first.host)
      expect(first.host.retired).toBe(true)
      expect(first.sink.released).toBe(1)
      expect(children[0].killed).toBe(true)
    } finally {
      log.mockRestore()
    }
  })

  it("keeps a retired host while its chat is busy", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      const first = await open("v3")
      first.sink.isBusy = true
      sync.mockReturnValue("d1")
      await open("v3")
      expect(first.sink.released).toBe(0)
      expect(children[0].killed).toBe(false)
      // Its last session leaves: the retired host ends.
      first.hs.drop()
      expect(children[0].killed).toBe(true)
    } finally {
      log.mockRestore()
    }
  })

  it("keeps a V3 listing's kiro-cli for the next chat, started with the chat environment", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      const listing = await hosts.pool.acquireForListing("v3")
      expect(await listing.request("session/list", {})).toEqual({})
      listing.release()
      expect(children[0].killed).toBe(false)
      const env = spawn.mock.calls[0][2].env as NodeJS.ProcessEnv
      expect(env.SDPM_DECK_ROOT).toBeTruthy()
      expect(env.SDPM_OUTPUT_DIR).toBe(env.SDPM_DECK_ROOT)
      expect(sync).toHaveBeenCalledTimes(1)
      await open("v3")
      expect(spawn).toHaveBeenCalledTimes(1)
      // A listing with a live host starts nothing.
      await hosts.pool.acquireForListing("v3")
      expect(spawn).toHaveBeenCalledTimes(1)
    } finally {
      log.mockRestore()
    }
  })

  it("kills a V2 listing's kiro-cli when the listing is done", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {})
    try {
      const listing = await hosts.pool.acquireForListing("v2")
      listing.release()
      expect(children[0].killed).toBe(true)
    } finally {
      log.mockRestore()
    }
  })
})

describe("exit and steer", () => {
  it("tells every sink when the kiro-cli exits", async () => {
    const a = await open("v3")
    const b = await open("v3")
    children[0].kill()
    await settle()
    expect(a.sink.exits).toEqual([null])
    expect(b.sink.exits).toEqual([null])
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
