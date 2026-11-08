// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The chat registry: a new chat is reachable under the client id (C) and its kiro session id (K,
 * what the deck's `.session` stores); a release drops every id of a chat; a deck's saved kiro
 * session is opened (or its live chat reused) under the client's id too, and only ids the chat
 * holds are kept; every chat gets a kiro-cli of its own, on V3 as on V2 (the fourth ends the least
 * recently active idle one, never a busy one, and it reopens its session on its next message); a
 * start that fails
 * (another mode, a failed sdpm server, no sign-in, an early exit) registers nothing; the
 * configured engine starts kiro-cli (V3 without acp-config.json), and an engine switch ends the
 * idle deck chats of the other engine (a busy one at the end of its period) and keeps chats
 * without a deck; a V2 kiro-cli that opened a composer session ends once its chat is idle; a deck's
 * `.session-engine` tells when its
 * session also ran on the other engine; a prompt to a chat still answering is refused; kiro-cli's
 * own requests are answered (permissions by option kind, the rest with Method not found) and
 * never taken for answers; setup requests time out and follow the caller's abort. A deck a tool
 * result names gets the session's `.session` (and a fork's origin) once, with or without a
 * listener; a released chat drops its pending origin. A fork cancelled once it exists is deleted
 * before its kiro-cli is killed; listing the stored sessions uses a live kiro-cli of the engine,
 * else a short-lived one (V2 needs none). A chat's model and effort change at once on an idle
 * chat (V3 set_config_option, V2 set_model), or are held and
 * sent right before the next session/prompt; a choice outside the offered models and levels is
 * refused; the reported list is kept in acp-models.json and listed without a kiro-cli; V3 leaves
 * the composer's model out of its definition. The work period, turns and steers are chat.test.ts's.
 * kiro-cli is replaced by the fake child (src/test/fakeKiro.ts).
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { BufferedEvent } from "./conversation/events"
import type { SessionOrigin } from "./kiro-sessions.types"
import { FAKE_MODELS, FakeChild, settle, tick } from "../../test/fakeKiro"
import { installFakeProcesses } from "../../test/fakeProcesses"

const { spawn, execFile, execFileSync } = vi.hoisted(() => ({ spawn: vi.fn(), execFile: vi.fn(), execFileSync: vi.fn() }))
vi.mock("child_process", () => ({ spawn, execFile, execFileSync, default: { spawn, execFile, execFileSync } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn(() => "d0") }))

const isEnd = (e: BufferedEvent) => e.event.kind === "end"
const payloadOf = (e: BufferedEvent) => e.event.payload as Record<string, unknown> | undefined

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

describe("process map", () => {
  it("registers a new chat's process under the client id and its kiro session id", async () => {
    const { chat: ps } = await acp.createNewProcessFor("C1")
    expect(ps.sessionId).toBe("K1")
    expect(acp.hasProcess("C1")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(true)

    // Reopening the deck sends with K: the live process is reused, no second kiro-cli.
    expect((await acp.openDeckSession("K1", "d1", "K1", "sdpm-orchestrator")).chat).toBe(ps)
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
    await settle()
    expect(children[0].killed).toBe(true)
  })

  it("restores a deck's saved kiro session under the client's own id as well", async () => {
    const { chat: ps, outcome } = await acp.openDeckSession("D0", "d0", "K9", "sdpm-orchestrator")
    expect(outcome).toBe("resumed")
    expect(ps.sessionId).toBe("K9")
    expect(acp.hasProcess("D0")).toBe(true)
    expect(acp.hasProcess("K9")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(false)
    expect((await acp.openDeckSession("D0", "d0", "K9", "sdpm-orchestrator")).chat).toBe(ps)
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("reuses the live process of the saved kiro session for another client id, which then sends without a spawn", async () => {
    const { chat: ps } = await acp.createNewProcessFor("C1")
    const opened = await acp.openDeckSession("D0", "d0", "K1", "sdpm-orchestrator")
    expect(opened).toMatchObject({ chat: ps, outcome: "resumed" })
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
    const { chat: ps, outcome } = await acp.openDeckSession("D0", "d0", "OLD", "sdpm-orchestrator")
    expect(outcome).toBe("created")
    expect(ps.sessionId).toBe("K1")
    expect(acp.hasProcess("D0")).toBe(true)
    expect(acp.hasProcess("K1")).toBe(true)
    expect(acp.hasProcess("OLD")).toBe(false)
    // Another tab opens the deck by its new .session: the same process.
    expect((await acp.openDeckSession("D1", "d0", "K1", "sdpm-orchestrator")).chat).toBe(ps)
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
      await settle()
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
    await settle()
    expect(children[0].killed).toBe(true)
    expect(acp.hasProcess("K9")).toBe(false)
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
    await settle()
    expect(children[0].killed).toBe(true)
    expect(acp.hasProcess("C1")).toBe(false)
  })

  it.each(["v2", "v3"] as const)("fails with mcp_failed when the %s sdpm server reports failed, and registers nothing", async (engine) => {
    useEngine(engine)
    nextChild((child) => { child.mcpState = "failed" })
    expect(await acp.createNewProcessFor("C1").catch((e: unknown) => e)).toMatchObject({ code: "mcp_failed" })
    await settle()
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

  it.each([
    ["v2", "session/new", null],
    ["v3", "session/new", null],
    ["v2", "session/load", "K9"],
    ["v3", "session/load", "K9"],
  ] as const)("fails with agent_start_failed when the %s kiro-cli exits during %s, and registers nothing", async (engine, method, saved) => {
    useEngine(engine)
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    try {
      nextChild((child) => { child.silent.add(method) })
      const pending = acp.openDeckSession("C1", "d1", saved, "sdpm-orchestrator").catch((e: unknown) => e)
      await settle()
      expect(children[0].requests.map((r) => r.method)).toContain(method)
      children[0].kill()
      expect(await pending).toMatchObject({ code: "agent_start_failed" })
      await settle()
      for (const id of ["C1", "K1", "K9"]) expect(acp.hasProcess(id)).toBe(false)
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
    const { chat: fresh } = await acp.createNewProcessFor("C1")
    const reopened = (await acp.openDeckSession("C2", "d1", "K9", "sdpm-orchestrator")).chat
    const created = (await acp.openDeckSession("C3", "d2", null, "sdpm-orchestrator")).chat
    expect([fresh.deckBound, reopened.deckBound, created.deckBound]).toEqual([false, true, true])

    acp.terminateIdleProcesses("v2")
    expect(children.map((c) => c.killed)).toEqual([false, false, false])
    acp.terminateIdleProcesses("v3")
    await settle()
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

  it("keeps a deck chat whose next prompt is being prepared when a hold ends its period after the switch", async () => {
    const { chat } = await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
    const child = children[0]
    const first = await acp.sendPrompt("C1", "build")
    first.send()
    await settle()
    // Chosen during the turn: applied before the next prompt, whose model change kiro-cli answers late.
    await acp.chooseSessionModel("C1", { model: "m-plain" })
    const release = chat.hold({ cancel: () => {}, dropped: () => {} })
    child.endTurn()
    await settle()
    child.silent.add("session/set_model")
    const next = acp.sendPrompt("C1", "next")
    await settle()
    useEngine("v3")
    acp.terminateIdleProcesses("v3")
    release()
    await settle()
    expect(child.killed).toBe(false)
    expect(acp.hasProcess("C1")).toBe(true)

    const setModel = child.requests.find((r) => r.method === "session/set_model")!
    child.send({ id: setModel.id, result: {} })
    const prompted = await next
    prompted.send()
    await settle()
    child.endTurn()
    await settle()
    expect(child.killed).toBe(true)
    expect(acp.hasProcess("C1")).toBe(false)
  })

  it("releases a deck chat whose prepare a Stop aborted after the switch, so its next message opens on the new engine", async () => {
    const { chat } = await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
    const child = children[0]
    const first = await acp.sendPrompt("C1", "build")
    first.send()
    await settle()
    await acp.chooseSessionModel("C1", { model: "m-plain" })
    const release = chat.hold({ cancel: () => {}, dropped: () => {} })
    child.endTurn()
    await settle()
    child.silent.add("session/set_model")
    const start = acp.beginStart("C1")
    const next = acp.sendPrompt("C1", "next", { signal: start.signal }).catch((e: unknown) => e)
    await settle()
    useEngine("v3")
    acp.terminateIdleProcesses("v3")
    release()
    await settle()
    expect(acp.hasProcess("C1")).toBe(true)

    acp.cancelSession("C1")
    const setModel = child.requests.find((r) => r.method === "session/set_model")!
    child.send({ id: setModel.id, result: {} })
    expect(await next).toMatchObject({ name: "AbortError" })
    start.end()
    await settle()
    expect(acp.hasProcess("C1")).toBe(false)
    expect(child.killed).toBe(true)
    await acp.openDeckSession("C1", "d1", "K9", "sdpm-orchestrator")
    expect(spawn.mock.calls.at(-1)![1]).toEqual(["acp", "--agent-engine", "v3"])
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
    const { chat: ps, outcome } = await acp.openDeckSession("C1", "d1", "sess_gone", "sdpm-orchestrator")
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
    const { chat: ps, outcome } = await acp.openForkedSession("F1", "sdpm-orchestrator", { onPhase: (phase) => { phases.push(phase) } })
    expect(outcome).toBe("created")
    expect(ps.sessionId).toBe("F1")
    expect(ps.deckBound).toBe(false)
    expect(phases[0]).toBe("starting")
    expect(await acp.openForkedSession("F1", "sdpm-orchestrator")).toMatchObject({ chat: ps, outcome: "resumed" })
  })
})

describe("forks and listing", () => {
  it("forks on V3 and registers the fork under its id", async () => {
    useEngine("v3")
    const phases: string[] = []
    const { chat: ps, sessionId, outcome } = await acp.forkSession("sess_src", "sdpm-orchestrator", { onPhase: (phase) => { phases.push(phase) } })
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
      await settle()
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
      await settle()
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
    const opened = child.requests.length
    expect(methods(child)).not.toContain("session/set_config_option")
    const prompted = await acp.sendPrompt("N1", "hello")
    prompted.send()
    await settle()
    expect(child.requests.slice(opened).map((r) => [r.method, r.params.value])).toEqual([
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

})

describe("one kiro-cli per chat", () => {
  const log = () => vi.spyOn(console, "log").mockImplementation(() => {})

  beforeEach(() => useEngine("v3"))

  it("gives V3 chats a kiro-cli each, as V2's", async () => {
    const a = await acp.createNewProcessFor("C1")
    const b = await acp.createNewProcessFor("C2")
    expect(spawn).toHaveBeenCalledTimes(2)
    expect(a.chat.hs.host).not.toBe(b.chat.hs.host)
    expect([a.chat.sessionId, b.chat.sessionId]).toEqual(["K1", "K2"])
  })

  it("ends the least recently active idle V3 chat for a fourth, never a busy one, and reopens its session on its next message", async () => {
    const restore = log()
    vi.useFakeTimers({ toFake: ["Date"] })
    try {
      // After the fake kiro-cli's sessions were created (2026-01-01), so a load counts as resumed.
      const at = Date.parse("2026-11-08T00:00:00.000Z")
      for (let i = 1; i <= 3; i++) {
        vi.setSystemTime(at + 1000 * i)
        await acp.createNewProcessFor(`C${i}`)
      }
      // C1 is the least recently active, but busy.
      const busy = await acp.sendPrompt("C1", "count")
      busy.send()
      await settle()
      vi.setSystemTime(at + 10_000)
      await acp.createNewProcessFor("C4")
      expect(children.map((c) => c.killed)).toEqual([false, true, false, false])
      expect(acp.hasProcess("C2")).toBe(false)
      expect(acp.isSessionRunning("C1")).toBe(true)
      children[0].endTurn()
      await settle()
      expect(acp.getBufferedEvents("C1").at(-1)?.event).toMatchObject({ kind: "end", stopReason: "end_turn" })

      // C2's next message opens its kiro session again in a new kiro-cli.
      const reopened = await acp.createNewProcessFor("C2")
      expect(reopened).toMatchObject({ resumed: true })
      expect(children.at(-1)!.requests.at(-1)).toMatchObject({ method: "session/load", params: { sessionId: "K2" } })
    } finally {
      vi.useRealTimers()
      restore.mockRestore()
    }
  })

  it("lists V2's stored sessions without starting kiro-cli", async () => {
    useEngine("v2")
    const { adapterFor } = await import("./acp/engine")
    const sessions = await acp.withEngineConnection("v2", (connect) => adapterFor("v2").listStoredSessions({ env: { KIRO_HOME: configDir } as unknown as NodeJS.ProcessEnv, connect }))
    expect(sessions).toEqual([])
    expect(spawn).not.toHaveBeenCalled()
  })
})

describe("unseen periods", () => {
  const quiet = () => vi.spyOn(console, "log").mockImplementation(() => {})
  /** What /api/agent/stream writes for `id`, read to its end (null: `{running: false}`). */
  async function stream(id: string) {
    const opened = acp.openStream(id)
    if (!opened) return null
    const { createSSEStream } = await import("./sse-bridge")
    const text = await new Response(createSSEStream(opened)).text()
    return text.split("\n\n").filter(Boolean).map((block) => JSON.parse(block.split("\n").find((l) => l.startsWith("data: "))!.slice(6)))
  }
  /** A period on `clientId` whose stream nobody read, with one text, ended. */
  async function unreadPeriod(clientId: string, child: FakeChild, sessionId: string, text = "the reply") {
    const prompted = await acp.sendPrompt(clientId, "hello")
    prompted.send()
    child.update(sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text } })
    await settle()
    child.endTurn("end_turn", sessionId)
    await settle()
  }
  const texts = (events: Record<string, unknown>[] | null) => (events ?? []).flatMap((e) => {
    const delta = (e.event as { contentBlockDelta?: { delta: { text: string } } } | undefined)?.contentBlockDelta
    return delta ? [delta.delta.text] : []
  })

  it("replays a finished period no stream delivered once; the next /stream finds nothing", async () => {
    await acp.createNewProcessFor("C1")
    await unreadPeriod("C1", children[0], "K1")
    const replayed = await stream("C1")
    expect(texts(replayed)).toEqual(["the reply"])
    expect(replayed?.at(-1)).toEqual({ work: { state: "idle", how: "finished" } })
    expect(await stream("C1")).toBeNull()
  })

  it("leaves nothing to replay when the invoke stream wrote the period's end", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello")
    const { createSSEStream } = await import("./sse-bridge")
    const body = new Response(createSSEStream({ subscribe: prompted.subscribe, replay: acp.getBufferedEvents("C1", prompted.replayFrom - 1), onEnd: prompted.onEnd })).text()
    prompted.send()
    await settle()
    children[0].endTurn()
    await body
    expect(await stream("C1")).toBeNull()
  })

  it("keeps a period whose replay was cancelled before its end for the next /stream", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello")
    prompted.send()
    await settle()
    const { createSSEStream } = await import("./sse-bridge")
    const live = createSSEStream(acp.openStream("C1")!)
    await live.cancel()
    children[0].endTurn()
    await settle()
    expect((await stream("C1"))?.length).toBeGreaterThan(0)
    expect(await stream("C1")).toBeNull()
  })

  it("replays it after the chat was released: the cap on V3, a kiro-cli exit", async () => {
    const restore = quiet()
    try {
      // V3: the fourth chat ends the least recently active idle one.
      useEngine("v3")
      await acp.createNewProcessFor("L1")
      await unreadPeriod("L1", children[0], "K1", "ended by the cap")
      for (let i = 2; i <= 4; i++) await acp.createNewProcessFor(`L${i}`)
      await settle()
      expect(children[0].killed).toBe(true)
      expect(texts(await stream("K1"))).toEqual(["ended by the cap"])
      expect(await stream("K1")).toBeNull()

      // An exit.
      const last = children.at(-1)!
      await unreadPeriod("L4", last, "K4", "before the exit")
      last.kill()
      await settle()
      expect(texts(await stream("L4"))).toEqual(["before the exit"])
    } finally {
      restore.mockRestore()
    }
  })

  it("replays a kiro-cli exit's period with agent_exited", async () => {
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "hello")
    prompted.send()
    await settle()
    children[0].kill()
    await settle()
    expect((await stream("C1"))?.at(-1)).toMatchObject({ status: "error", code: "agent_exited" })
  })

  it("keeps at most 50 such periods: the 51st drops every id of the oldest", async () => {
    const restore = quiet()
    try {
      for (let i = 1; i <= 51; i++) {
        await acp.createNewProcessFor(`C${i}`)
        await unreadPeriod(`C${i}`, children[i - 1], `K${i}`)
        acp.terminateProcess(`C${i}`)
      }
      expect(await stream("C1")).toBeNull()
      expect(await stream("K1")).toBeNull()
      expect(await stream("K2")).not.toBeNull()
      expect(await stream("C51")).not.toBeNull()
    } finally {
      restore.mockRestore()
    }
  })
})

describe("Stop during start", () => {
  const promptsSent = (child: FakeChild) => child.requests.filter((r) => r.method === "session/prompt")

  it.each(["v2", "v3"] as const)("kills a cold %s kiro-cli no other chat waits for, and sends no prompt", async (engine) => {
    useEngine(engine)
    spawn.mockImplementationOnce((_command: string, args: string[]) => {
      const child = new FakeChild("K1", locked, args)
      child.silent.add("initialize")
      children.push(child)
      return child
    })
    const start = acp.beginStart("C1")
    const pending = acp.createNewProcessFor("C1", "sdpm-orchestrator", { signal: start.signal }).catch((e: unknown) => e)
    await settle()
    acp.cancelSession("C1")
    expect(await pending).toMatchObject({ name: "AbortError" })
    expect(start.stoppedByUser()).toBe(true)
    start.end()
    await settle()
    expect(children[0].killed).toBe(true)
    expect(promptsSent(children[0])).toEqual([])
    expect(acp.hasProcess("C1")).toBe(false)
  })

  it("sends no prompt when Stop comes after the chat opened, before its period", async () => {
    await acp.createNewProcessFor("C1")
    const start = acp.beginStart("C1")
    acp.cancelSession("C1")
    await expect(acp.sendPrompt("C1", "hello", { signal: start.signal })).rejects.toMatchObject({ name: "AbortError" })
    start.end()
    expect(promptsSent(children[0])).toEqual([])
    expect(acp.isSessionRunning("C1")).toBe(false)
  })

  it("tells Stop from a client that went away, and Stop of all chats aborts every start", async () => {
    const outer = new AbortController()
    const gone = acp.beginStart("C1", outer.signal)
    outer.abort()
    expect(gone.signal.aborted).toBe(true)
    expect(gone.stoppedByUser()).toBe(false)
    gone.end()

    const a = acp.beginStart("A")
    const b = acp.beginStart("B")
    acp.cancelAll()
    expect([a.signal.aborted, b.signal.aborted, a.stoppedByUser(), b.stoppedByUser()]).toEqual([true, true, true, true])
    a.end()
    b.end()
    // An ended start is not aborted by a later Stop.
    const c = acp.beginStart("C")
    c.end()
    acp.cancelSession("C")
    expect(c.signal.aborted).toBe(false)
  })
})
