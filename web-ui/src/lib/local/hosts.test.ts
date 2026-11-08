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
import { FAKE_OWN_PGID, installFakeProcesses } from "../../test/fakeProcesses"

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

let procs: ReturnType<typeof installFakeProcesses>

beforeEach(async () => {
  children = []
  nextSetup = null
  spawn.mockReset()
  procs = installFakeProcesses({ spawn, execFile, execFileSync })
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
    await settle()
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
    await settle()
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
      await settle()
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

describe("composer hosts", () => {
  const quiet = () => { vi.spyOn(console, "log").mockImplementation(() => {}); vi.spyOn(console, "warn").mockImplementation(() => {}) }
  const writeConfig = (config: Record<string, unknown>) => fs.writeFileSync(path.join(configDir, "acp-config.json"), JSON.stringify({ version: 2, ...config })) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir

  it.each([["v2", ["acp", "--agent", "sdpm-composer"]], ["v3", ["acp", "--agent-engine", "v3"]]] as const)(
    "starts a %s composer detached for sdpm-composer, without SDPM_LOCAL_COMPOSE even when the environment and acp-config.json set it",
    async (engine, args) => {
      quiet()
      vi.stubEnv("SDPM_LOCAL_COMPOSE", "1")
      writeConfig({ engine, env: { SDPM_LOCAL_COMPOSE: "1" } })
      await hosts.pool.acquireForComposer(engine)
      const [, spawnArgs, options] = spawn.mock.calls[0]
      expect(spawnArgs).toEqual(args)
      expect(options.detached).toBe(true)
      expect("SDPM_LOCAL_COMPOSE" in options.env).toBe(false)
      expect(options.env.SDPM_DECK_ROOT).toBeTruthy()
    },
  )

  it("gives a chat's kiro-cli SDPM_LOCAL_COMPOSE=1 and no detached", async () => {
    vi.stubEnv("SDPM_LOCAL_COMPOSE", "0")
    await open("v3")
    const options = spawn.mock.calls[0][2]
    expect(options.env.SDPM_LOCAL_COMPOSE).toBe("1")
    expect(options).not.toHaveProperty("detached")
  })

  it("lets a fifth composer wait until a composer's tree is gone; an abort while waiting leaves the queue", async () => {
    quiet()
    const four = await Promise.all([0, 1, 2, 3].map(() => hosts.pool.acquireForComposer("v3")))
    const waited = vi.fn()
    const controller = new AbortController()
    const given = hosts.pool.acquireForComposer("v3", { signal: controller.signal, onWait: waited }).catch((e: unknown) => e)
    const fifth = hosts.pool.acquireForComposer("v3", { onWait: waited })
    await settle()
    expect(spawn).toHaveBeenCalledTimes(4)
    expect(waited).toHaveBeenCalledTimes(2)
    controller.abort()
    expect(await given).toMatchObject({ name: "AbortError" })
    void four[0].end("SIGTERM")
    await settle()
    expect(children[0].killed).toBe(true)
    // The slot frees with the gone poll, then the fifth starts.
    await new Promise((r) => setTimeout(r, 150))
    const host = await fifth
    expect(spawn).toHaveBeenCalledTimes(5)
    expect(host.role).toBe("composer")
  })

  it("holds a composer's slot after its kiro-cli exits while its agent server lives, and SIGKILLs that group after 2 s", async () => {
    quiet()
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
    const composers = []
    for (let i = 0; i < 4; i++) {
      nextSetup = (child) => { child.addDescendant(); child.surviveTerm = true }
      const host = await hosts.pool.acquireForComposer("v3")
      await host.openSession("sdpm-composer", { kind: "new" }, { sink: new Sink("aux") })
      composers.push(host)
    }
    await settle()
    const kas = children[0].descendants[0]
    children[0].exit(1)
    await settle()
    // kiro-cli is gone, its KAS group is not: SIGTERM to both groups, the slot still taken.
    expect(procs.sent()).toEqual([[-kas.pgid, "SIGTERM"]])
    let fifth: unknown = null
    void hosts.pool.acquireForComposer("v3").then((h) => { fifth = h })
    await vi.advanceTimersByTimeAsync(1900)
    expect(fifth).toBeNull()
    expect(kas.dead).toBeFalsy()
    await vi.advanceTimersByTimeAsync(200)
    await settle()
    expect(procs.sent()).toContainEqual([-kas.pgid, "SIGKILL"])
    expect(kas.dead).toBe(true)
    await vi.advanceTimersByTimeAsync(200)
    await settle()
    expect(fifth).not.toBeNull()
  })

  it("neither counts nor releases composer hosts for the chat cap, and never lists through one", async () => {
    quiet()
    for (let i = 0; i < 4; i++) await hosts.pool.acquireForComposer("v3")
    for (let i = 0; i < 3; i++) await open("v3")
    await settle()
    expect(children.map((c) => c.killed)).toEqual([false, false, false, false, false, false, false])
    const listing = await hosts.pool.acquireForListing("v3")
    await listing.request("session/list", {})
    // A chat's kiro-cli answered the listing; no composer's.
    expect(children.slice(0, 4).every((c) => !c.requests.some((r) => r.method === "session/list"))).toBe(true)
    expect(spawn).toHaveBeenCalledTimes(7)
  })

  it("ends a chat's tree with its kiro-cli's pid and its own groups, never the Local server's group", async () => {
    quiet()
    nextSetup = (child) => {
      child.addDescendant() // V3's agent server
      child.descendants.push({ pid: 5_900_001, pgid: FAKE_OWN_PGID, ppid: child.pid }) // left in the server's group
    }
    const { host } = await open("v3")
    await settle()
    host.kill()
    await settle()
    const [kas, inOwn] = children[0].descendants
    expect(procs.sent()).toEqual(expect.arrayContaining([[-kas.pgid, "SIGTERM"], [inOwn.pid, "SIGTERM"], [children[0].pid, "SIGTERM"]]))
    expect(procs.sent().some(([target]) => target === -FAKE_OWN_PGID || target === process.pid)).toBe(false)
  })

  it("killAll reads the table once, SIGKILLs composer trees and SIGTERMs chat trees, skipping a reused pid", async () => {
    quiet()
    await open("v3")
    nextSetup = (child) => { child.addDescendant() }
    const composer = await hosts.pool.acquireForComposer("v3")
    await composer.openSession("sdpm-composer", { kind: "new" }, { sink: new Sink("aux") })
    await settle()
    const kas = children[1].descendants[0]
    // The KAS ended and its pid came back as an unrelated process: not signalled.
    const table = procs.table().replace(new RegExp(`^${kas.pid} (\\d+) \\d+ fake$`, "m"), `${kas.pid} $1 1 reused`)
    execFileSync.mockImplementationOnce(() => table)
    const before = procs.psCalls()
    procs.signals.length = 0
    hosts.pool.killAll()
    expect(procs.psCalls() - before).toBe(0)
    expect(execFileSync).toHaveBeenCalledTimes(1)
    expect(procs.sent()).toEqual([[children[0].pid, "SIGTERM"], [-children[1].pid, "SIGKILL"], [children[1].pid, "SIGKILL"]])
  })

  it("starts nothing and frees the slot when the abort comes right after the slot was handed over", async () => {
    quiet()
    const controller = new AbortController()
    const given = hosts.pool.acquireForComposer("v3", { signal: controller.signal }).catch((e: unknown) => e)
    controller.abort()
    expect(await given).toMatchObject({ name: "AbortError" })
    expect(spawn).not.toHaveBeenCalled()
    const waited = vi.fn()
    await Promise.all([0, 1, 2, 3].map(() => hosts.pool.acquireForComposer("v3", { onWait: waited })))
    expect(waited).not.toHaveBeenCalled()
  })

  it("killAll on Windows runs taskkill /T once per kiro-cli and reads no process table", async () => {
    quiet()
    const taskkill = vi.fn()
    const pool = new hosts.HostPool({ platform: "win32", taskkill })
    const chat = await pool.acquireForChat("v3", "sdpm-orchestrator")
    await chat.openSession("sdpm-orchestrator", { kind: "new" }, { sink: new Sink() })
    await pool.acquireForComposer("v3")
    await settle()
    const before = procs.psCalls()
    pool.killAll()
    expect(procs.psCalls()).toBe(before)
    expect(taskkill.mock.calls).toEqual([[children[0].pid], [children[1].pid]])
    expect(procs.sent()).toEqual([])
  })

  it("fails a composer open at once with agent_start_failed when its kiro-cli exits before the sdpm server is ready", async () => {
    quiet()
    nextSetup = (child) => { child.mcpState = "none" }
    const host = await hosts.pool.acquireForComposer("v3")
    const pending = host.openSession("sdpm-composer", { kind: "new" }, { sink: new Sink("aux") }).catch((e: unknown) => e)
    await settle()
    children[0].exit(9)
    expect(await pending).toMatchObject({ code: "agent_start_failed" })
  })
})
