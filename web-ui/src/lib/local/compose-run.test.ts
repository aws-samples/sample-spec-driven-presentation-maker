// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The compose run (compose-run.ts) through the chat registry, the host pool and fake kiro-cli
 * processes: one for the chat, one per composer kiro-cli the pool starts.
 *
 * - Dispatch: one composer kiro-cli per group, started for sdpm-composer, prompted with the
 *   deck's path on the orchestrator's model; the chat's kiro-cli gets no other session; both
 *   prompts go out before either answers; `taskStart` replaces the tool's result; the dispatch is
 *   recognised from a nameless V3 end and a titled V2 end; at most four groups of a task run.
 * - Group end: V3 closes and deletes the session, then SIGTERMs P and K; V2 SIGTERMs P and U.
 *   The task ends with `taskEnd` and one wake turn carrying `<compose_result>`.
 * - message_composer: a steer on that group's kiro-cli before the tool's own end; a message for a
 *   starting group goes into its first prompt; a late one into a follow-up prompt on the same
 *   kiro-cli; an ended or unknown group is not delivered and the orchestrator is told.
 * - Stop, twice and then the chat's exit; the settle timeout; a composer's exit and start
 *   failure; the chat's exit; the 60-minute timeout; a queued task; an invalid result; the
 *   output check; a compose period whose chat the cap released is replayed once (a closed tab).
 */
import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FakeChild, settle } from "../../test/fakeKiro"
import { installFakeProcesses } from "../../test/fakeProcesses"
import type { ChatEvent } from "./conversation/events"

const { spawn, execFile, execFileSync } = vi.hoisted(() => ({ spawn: vi.fn(), execFile: vi.fn(), execFileSync: vi.fn() }))
vi.mock("child_process", () => ({ spawn, execFile, execFileSync, default: { spawn, execFile, execFileSync } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn(() => "d0") }))

type Engine = "v2" | "v3"

let children: FakeChild[]
let setups: ((child: FakeChild) => void)[]
let procs: ReturnType<typeof installFakeProcesses>
let acp: typeof import("./acp-process")
let deckRoot: string
let configDir: string
let deck: string

beforeEach(async () => {
  deckRoot = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-compose-run-"))) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_DECK_ROOT", deckRoot)
  deck = path.join(deckRoot, "20261108-2111-spike") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
  fs.mkdirSync(path.join(deck, "slides"), { recursive: true }) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
  children = []
  setups = []
  spawn.mockReset()
  procs = installFakeProcesses({ spawn, execFile, execFileSync })
  spawn.mockImplementation((_command: string, args: string[]) => {
    const child = new FakeChild(`K${children.length + 1}`, new Set(), args)
    if (children.length > 0) child.addDescendant() // a composer's agent server (V3) or MCP server (V2)
    setups.shift()?.(child)
    children.push(child)
    return child
  })
  configDir = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-compose-config-")) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", configDir)
  vi.spyOn(console, "log").mockImplementation(() => {})
  vi.spyOn(console, "warn").mockImplementation(() => {})
  vi.resetModules()
  acp = await import("./acp-process")
})

afterEach(() => {
  for (const child of children) child.kill()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  fs.rmSync(deckRoot, { recursive: true, force: true })
  fs.rmSync(configDir, { recursive: true, force: true })
})

function setEngine(engine: Engine) {
  fs.writeFileSync(path.join(configDir, "acp-config.json"), JSON.stringify({ version: 2, engine })) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
}

const payloads = (events: ChatEvent[]) => events.flatMap((e) => (e.kind === "data" ? [e.payload as Record<string, unknown>] : []))
const kinds = (events: ChatEvent[], key: string) => payloads(events).filter((p) => key in p).map((p) => p[key] as Record<string, unknown>)
const methods = (child: FakeChild) => child.requests.map((r) => r.method)
const prompts = (child: FakeChild) => child.requests.filter((r) => r.method === "session/prompt").map((r) => ((r.params.prompt as { text: string }[])[0]).text)
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** A dispatched result for `groups` (slugs per group). */
function dispatched(groups: string[][], taskId = "0123456789ab", deckId = deck, format = "pptx") {
  return {
    status: "dispatched", task_id: taskId, deck_id: deckId, output_format: format,
    slide_groups: groups.map((slugs, i) => ({ group: i + 1, slugs, instruction: `Compose ${slugs.join(" and ")}.` })),
    outline_slugs: groups.flat(),
    notice: "Running in the background.",
  }
}

/** The orchestrator's MCP tool call and its end, in the engine's shape (V3's end has no name, V2's the update title). */
function callTool(child: FakeChild, engine: Engine, id: string, name: string, input: Record<string, unknown>, result: unknown, opts: { end?: boolean } = {}) {
  if (engine === "v3") {
    child.update("K1", { sessionUpdate: "tool_call", toolCallId: id, title: `@sdpm/${name}`, kind: "other", status: "pending", rawInput: { tool_id: `sdpm::${name}`, arguments: input }, _meta: { kiro: { serverName: "sdpm" } } })
    if (opts.end !== false) child.update("K1", { sessionUpdate: "tool_call_update", toolCallId: id, status: "completed", rawOutput: { response: typeof result === "string" ? result : JSON.stringify(result) }, _meta: { kiro: { serverName: "sdpm" } } })
  } else {
    child.update("K1", { sessionUpdate: "tool_call", toolCallId: id, title: `Running: @sdpm/${name}`, rawInput: input, _meta: { kiro: { toolName: name, mcpServerName: "sdpm" } } })
    if (opts.end !== false) child.update("K1", { sessionUpdate: "tool_call_update", toolCallId: id, status: "completed", title: `Running: @sdpm/${name}`, rawOutput: { items: [{ Json: { content: [{ type: "text", text: typeof result === "string" ? result : JSON.stringify(result) }] } }] } })
  }
}

function endCall(child: FakeChild, engine: Engine, id: string, name: string, result: unknown) {
  if (engine === "v3") child.update("K1", { sessionUpdate: "tool_call_update", toolCallId: id, status: "completed", rawOutput: { response: typeof result === "string" ? result : JSON.stringify(result) }, _meta: { kiro: { serverName: "sdpm" } } })
  else child.update("K1", { sessionUpdate: "tool_call_update", toolCallId: id, status: "completed", title: `Running: @sdpm/${name}`, rawOutput: { items: [{ Json: { content: [{ type: "text", text: String(result) }] } }] } })
}

/** A chat whose turn dispatched `groups`; the orchestrator's turn ends unless `keepTurn`. */
async function compose(engine: Engine, groups: string[][], opts: { keepTurn?: boolean; result?: unknown } = {}) {
  setEngine(engine)
  const { chat } = await acp.createNewProcessFor("C1")
  const prompted = await acp.sendPrompt("C1", "compose")
  const events: ChatEvent[] = []
  prompted.subscribe((entry) => { events.push(entry.event) })
  prompted.send()
  await settle()
  const orch = children[0]
  callTool(orch, engine, "disp", "compose_slides", { deck_id: deck, slide_groups: groups.map((slugs) => ({ slugs, instruction: "x" })) }, opts.result ?? dispatched(groups))
  await settle()
  if (!opts.keepTurn) {
    orch.endTurn("end_turn", "K1")
    await settle()
  }
  await settle()
  return { chat, orch, events, composers: () => children.slice(1) }
}

/** A composer's sessionId (its child's first session). */
const sid = (child: FakeChild) => child.created[0]

describe("dispatch", () => {
  it.each(["v3", "v2"] as const)("%s: one composer kiro-cli per group, prompted at once with the deck's path on the chat's model", async (engine) => {
    const { orch, events, composers } = await compose(engine, [["cover"], ["why"]])
    expect(composers()).toHaveLength(2)
    for (const [i, child] of composers().entries()) {
      expect(child.args).toEqual(engine === "v3" ? ["acp", "--agent-engine", "v3"] : ["acp", "--agent", "sdpm-composer"])
      if (engine === "v3") expect(child.requests.find((r) => r.method === "session/new")!.params._meta).toEqual({ kiro: { modeId: "sdpm-composer" } })
      expect(methods(child)).toEqual(["initialize", "session/new", engine === "v3" ? "session/set_config_option" : "session/set_model", "session/prompt"])
      expect(prompts(child)[0]).toBe(`deck_id: ${deck}\nassigned_slugs: ${["cover", "why"][i]}\nmode: pptx\ntask_instruction: Compose ${["cover", "why"][i]}.`)
    }
    // Both prompts are out, neither answered; the chat's kiro-cli carries only its own session.
    expect(composers().every((c) => c.prompts.length === 1)).toBe(true)
    expect(orch.requests.filter((r) => r.method === "session/new")).toHaveLength(1)
    expect(spawn.mock.calls.slice(1).every((call) => call[2].detached === true)).toBe(true)
    expect(kinds(events, "taskStart")).toEqual([{ toolUseId: "disp", name: "compose_slides", taskId: "0123456789ab" }])
    expect(kinds(events, "toolResult").filter((r) => r.toolUseId === "disp")).toEqual([])
    expect(kinds(events, "toolStream").filter((s) => (s.data as { status?: string }).status === "starting").map((s) => s.data))
      .toEqual([{ group: 1, total_groups: 2, slugs: "cover", status: "starting" }, { group: 2, total_groups: 2, slugs: "why", status: "starting" }])
    expect(acp.isSessionRunning("C1")).toBe(true)
  })

  it("goes on with the prompt when the model cannot be set", async () => {
    setups = [() => {}, (c) => { c.failing.add("session/set_config_option") }]
    const { composers } = await compose("v3", [["a"]])
    expect(methods(composers()[0]).slice(-2)).toEqual(["session/set_config_option", "session/prompt"])
  })

  it("starts four groups of six, and the others as groups end", async () => {
    const { composers } = await compose("v3", [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]])
    expect(composers()).toHaveLength(4)
    composers()[0].endTurn()
    await settle()
    await wait(150)
    await settle()
    expect(composers()).toHaveLength(5)
    expect(prompts(composers()[4])[0]).toContain("assigned_slugs: e")
  })

  it("starts nothing for a compose_slides end whose tool_use had another name, and shows an error answer as a result", async () => {
    setEngine("v3")
    await acp.createNewProcessFor("C1")
    const prompted = await acp.sendPrompt("C1", "compose")
    const events: ChatEvent[] = []
    prompted.subscribe((entry) => { events.push(entry.event) })
    prompted.send()
    await settle()
    const orch = children[0]
    callTool(orch, "v3", "x1", "list_styles", {}, dispatched([["a"]]))
    callTool(orch, "v3", "x2", "compose_slides", {}, { status: "error", errors: ["no outline"] })
    await settle()
    expect(children).toHaveLength(1)
    expect(kinds(events, "taskStart")).toEqual([])
    expect(kinds(events, "toolResult").map((r) => [r.toolUseId, r.name, r.status])).toEqual([["x1", "list_styles", "success"], ["x2", "compose_slides", "success"]])
  })

  it("refuses a dispatched result whose deck is not a deck of this server, and tells the orchestrator", async () => {
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-not-a-deck-")) // nosemgrep: path-join-resolve-traversal — constant prefix
    try {
      const { orch, events } = await compose("v3", [["a"]], { result: dispatched([["a"]], "0123456789ab", outside) })
      expect(children).toHaveLength(1)
      expect(kinds(events, "toolResult").find((r) => r.toolUseId === "disp")).toMatchObject({ status: "error", name: "compose_slides" })
      // Delivered while the turn ran: a hidden steer, else the next turn.
      const steered = orch.requests.filter((r) => r.method === "_session/steer").map((r) => r.params.message as string)
      expect(steered.join("")).toContain('<compose_result task="0123456789ab" status="failed">')
      expect(steered.join("")).toContain("deck_id is not a deck of this server")
    } finally {
      fs.rmSync(outside, { recursive: true, force: true })
    }
  })
})

describe("group end and task end", () => {
  it("V3: closes and deletes each composer's session, SIGTERMs P and K, and wakes the orchestrator once", async () => {
    const { orch, events, composers } = await compose("v3", [["cover"], ["why"]])
    const [c1, c2] = composers()
    c1.update(sid(c1), { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "Cover done." } })
    c1.endTurn()
    await settle()
    expect(methods(c1).slice(-2)).toEqual(["session/close", "session/delete"])
    await settle()
    expect(procs.sent()).toEqual(expect.arrayContaining([[-c1.pid, "SIGTERM"], [-c1.descendants[0].pgid, "SIGTERM"]]))
    expect(orch.prompts).toHaveLength(0)
    c2.endTurn()
    await settle()
    const ends = kinds(events, "taskEnd")
    expect(ends).toHaveLength(1)
    expect(ends[0]).toMatchObject({ toolUseId: "disp", taskId: "0123456789ab", name: "compose_slides", status: "completed" })
    const report = JSON.parse(ends[0].content as string)
    expect(report).toMatchObject({ status: "completed", generated_slides: ["cover", "why"], build: "stale", summaries: { cover: "Cover done." } })
    const wake = prompts(orch).at(-1)!
    expect(wake.startsWith('<compose_result task="0123456789ab" status="completed">')).toBe(true)
    expect(kinds(events, "turn").map((t) => t.why)).toEqual(["wake"])
    expect(kinds(events, "toolStream").filter((s) => ["done", "error"].includes((s.data as { status?: string }).status ?? "")).map((s) => s.data)).toEqual([
      { group: 1, slugs: "cover", status: "done" }, { group: 2, slugs: "why", status: "done" },
    ])
  })

  it("V2: SIGTERMs P and U without closing (V2 has no session/close)", async () => {
    const { composers } = await compose("v2", [["cover"]])
    const [c1] = composers()
    c1.endTurn()
    await settle()
    await settle()
    expect(methods(c1)).not.toContain("session/close")
    expect(procs.sent()).toEqual(expect.arrayContaining([[-c1.pid, "SIGTERM"], [-c1.descendants[0].pgid, "SIGTERM"]]))
  })

  it("reports one group's output older than a slide as stale, newer as built; an HTML deck gets the run_python sentence", async () => {
    fs.writeFileSync(path.join(deck, "output.pptx"), "x") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
    fs.utimesSync(path.join(deck, "output.pptx"), new Date(1000), new Date(1000)) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
    fs.writeFileSync(path.join(deck, "slides", "a.json"), "{}") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
    const first = await compose("v3", [["a"]])
    first.composers()[0].endTurn()
    await settle()
    expect(JSON.parse(kinds(first.events, "taskEnd")[0].content as string).build).toBe("stale")

    // A newer output: no build key (a second task of the same chat, after the wake turn).
    first.orch.endTurn("end_turn", "K1")
    await settle()
    fs.writeFileSync(path.join(deck, "output.pptx"), "y") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
    const prompted = await acp.sendPrompt("C1", "again")
    const events: ChatEvent[] = []
    prompted.subscribe((entry) => { events.push(entry.event) })
    prompted.send()
    await settle()
    callTool(first.orch, "v3", "disp2", "compose_slides", {}, dispatched([["a"]], "00000000000b"))
    await settle()
    first.orch.endTurn("end_turn", "K1")
    await settle()
    children.at(-1)!.endTurn()
    await settle()
    expect(JSON.parse(kinds(events, "taskEnd")[0].content as string)).not.toHaveProperty("build")
  })

  it("an HTML deck with two groups gets the run_python rebuild sentence", async () => {
    const { events, composers } = await compose("v3", [["a"], ["b"]], { result: dispatched([["a"], ["b"]], "0123456789ab", deck, "html") })
    for (const c of composers()) c.endTurn()
    await settle()
    const report = JSON.parse(kinds(events, "taskEnd")[0].content as string)
    expect(report.build).toBe("stale")
    expect(report.notice).toContain(`run_python(purpose="Rebuild output.html", deck_id="${deck}"`)
    expect(prompts(composers()[0])[0]).toContain("mode: html")
  })

  it("fails a group whose composer exits, goes on with the others, and reports partial", async () => {
    const { events, orch, composers } = await compose("v3", [["a"], ["b"]])
    const [c1, c2] = composers()
    c1.exit(7)
    await settle()
    c2.endTurn()
    await settle()
    const report = JSON.parse(kinds(events, "taskEnd")[0].content as string)
    expect(report).toMatchObject({ status: "partial", generated_slides: ["b"], failed_groups: [{ group_index: 1, slugs: ["a"], error: "kiro-cli exited (code 7)" }] })
    expect(prompts(orch).at(-1)).toContain('status="completed"')
  })

  it.each([["agent_start_failed", (c: FakeChild) => { c.failing.add("initialize") }], ["agent_definition_rejected", (c: FakeChild) => { c.newMode = "kiro_default" }]] as const)(
    "fails a group whose composer cannot start (%s), and ends its tree",
    async (_code, setup) => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
      setups = [() => {}, setup]
      const { events, composers } = await compose("v3", [["a"], ["b"]])
      await vi.advanceTimersByTimeAsync(2100) // V3's grace for a rejected definition
      await settle()
      const [c1, c2] = composers()
      c2.endTurn()
      await settle()
      await settle()
      const report = JSON.parse(kinds(events, "taskEnd")[0].content as string)
      expect(report.failed_groups).toHaveLength(1)
      expect(report.failed_groups[0]).toMatchObject({ slugs: ["a"], error: expect.stringMatching(new RegExp(`^${_code}: `)) })
      expect(c1.killed).toBe(true)
    },
  )
})

describe("message_composer", () => {
  it("steers that group's kiro-cli before the tool's own end, and marks the card delivered", async () => {
    setups = [() => {}, (c) => { c.steerAnswer = { queued: true, messageId: "steer-1" } }]
    const { orch, events, composers } = await compose("v3", [["cover"], ["why"]])
    const prompted = await acp.sendPrompt("C1", "make the title blue")
    prompted.send()
    await settle()
    callTool(orch, "v3", "m1", "message_composer", { group: 1, text: "Make the title blue." }, null, { end: false })
    await settle()
    const [c1, c2] = composers()
    const steer = c1.requests.find((r) => r.method === "_session/steer")!
    expect(steer.params).toEqual({ sessionId: sid(c1), message: "Message from the orchestrator while you work: Make the title blue." })
    expect(methods(c2)).not.toContain("_session/steer")
    endCall(orch, "v3", "m1", "message_composer", "Sent to composer 1")
    await settle()
    expect(kinds(events, "toolResult").find((r) => r.toolUseId === "m1")).toMatchObject({ name: "message_composer", status: "success" })
  })

  it("puts a message for a starting group into its first prompt", async () => {
    setups = [() => {}, (c) => { c.silent.add("session/new") }]
    const { orch, composers } = await compose("v3", [["cover"]], { keepTurn: true })
    callTool(orch, "v3", "m1", "message_composer", { group: 1, text: "Add a subtitle." }, "Sent")
    await settle()
    const [c1] = composers()
    c1.silent.delete("session/new")
    const request = c1.requests.find((r) => r.method === "session/new")!
    c1.send({ method: "_kiro/mcp/status", params: { sessionId: "K2", servers: [{ name: "sdpm", status: "connected" }] } })
    c1.send({ id: request.id, result: { sessionId: "K2", modes: { currentModeId: "sdpm-composer", availableModes: [] }, configOptions: c1.configOptions("K2") } })
    await settle()
    expect(prompts(c1)[0]).toMatch(/task_instruction: Compose cover\.\n\nMessage from the orchestrator while you work: Add a subtitle\.$/)
  })

  it("sends a message kiro-cli had not injected as a follow-up prompt on the same kiro-cli, before its tree is ended", async () => {
    const { orch, composers } = await compose("v3", [["cover"]], { keepTurn: true })
    callTool(orch, "v3", "m1", "message_composer", { group: 1, text: "Late." }, "Sent")
    await settle()
    const [c1] = composers()
    c1.endTurn()
    await settle()
    expect(methods(c1).slice(-3)).toEqual(["_session/steer", "_session/steer/clear", "session/prompt"])
    expect(prompts(c1).at(-1)).toBe("Message from the orchestrator while you work: Late.")
    expect(c1.killed).toBe(false)
    c1.endTurn()
    await settle()
    await settle()
    expect(c1.killed).toBe(true)
  })

  it("does not deliver to an ended or unknown group, and tells the orchestrator which groups run", async () => {
    const { orch, events, composers } = await compose("v3", [["a"], ["b"]], { keepTurn: true })
    composers()[0].endTurn()
    await settle()
    callTool(orch, "v3", "m1", "message_composer", { group: 1, text: "x" }, "Sent")
    callTool(orch, "v3", "m2", "message_composer", { group: 9, text: "y" }, "Sent")
    await settle()
    expect(kinds(events, "toolResult").filter((r) => r.name === "message_composer").map((r) => [r.toolUseId, r.status])).toEqual([["m1", "error"], ["m2", "error"]])
    const steered = orch.requests.filter((r) => r.method === "_session/steer").map((r) => r.params.message as string)
    expect(steered).toEqual([
      '<message_composer_error group="1">No composer of group 1 is running. Running groups: 2 (b).</message_composer_error>',
      '<message_composer_error group="9">No composer of group 9 is running. Running groups: 2 (b).</message_composer_error>',
    ])
  })
})

describe("Stop", () => {
  it("cancels every composer, SIGTERMs each tree after its cancelled answer and SIGKILLs the rest at 1 s", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
    const { events, composers } = await compose("v3", [["a"], ["b"]])
    const [c1, c2] = composers()
    c2.surviveTerm = true
    acp.cancelSession("C1")
    expect(c1.cancelled).toEqual([sid(c1)])
    expect(c2.cancelled).toEqual([sid(c2)])
    c1.endTurn("cancelled")
    c2.endTurn("cancelled")
    await settle()
    await settle()
    expect(procs.sent()).toEqual(expect.arrayContaining([[-c1.pid, "SIGTERM"], [-c2.pid, "SIGTERM"], [-c2.descendants[0].pgid, "SIGTERM"]]))
    expect(c2.descendants[0].dead).toBeFalsy()
    const ends = kinds(events, "taskEnd")
    expect(ends.map((e) => e.status)).toEqual(["cancelled"])
    await vi.advanceTimersByTimeAsync(1000)
    await settle()
    expect(procs.sent()).toContainEqual([-c2.descendants[0].pgid, "SIGKILL"])
    expect(c2.descendants[0].dead).toBe(true)
    // Nothing that starts model work after Stop.
    for (const c of composers()) expect(methods(c).filter((m) => m === "session/prompt" || m === "_session/steer")).toHaveLength(1)
    // The period ended after taskEnd; the next message starts with the cancelled report.
    const end = events.findIndex((e) => e.kind === "end")
    expect(end).toBeGreaterThan(events.findIndex((e) => e.kind === "data" && "taskEnd" in e.payload))
    const next = await acp.sendPrompt("C1", "hello again")
    next.send()
    await settle()
    expect(prompts(children[0]).at(-1)).toMatch(/^<compose_result task="0123456789ab" status="cancelled">[\s\S]*the deck may be partly built[\s\S]*hello again$/)
  })

  it("aborts a starting composer on Stop and ends its tree with SIGKILL", async () => {
    setups = [() => {}, (c) => { c.silent.add("session/new") }]
    const { events, composers } = await compose("v3", [["a"]])
    const [c1] = composers()
    acp.cancelSession("C1")
    await settle()
    await settle()
    expect(procs.sent()).toContainEqual([-c1.pid, "SIGKILL"])
    expect(methods(c1)).not.toContain("session/prompt")
    expect(kinds(events, "taskEnd").map((e) => e.status)).toEqual(["cancelled"])
  })

  it("Stop twice, then the chat's exit: one taskEnd (failed), one SIGKILL per group, one cancel per composer", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
    const { events, orch, composers } = await compose("v3", [["a"], ["b"]])
    acp.cancelSession("C1")
    acp.cancelSession("C1")
    orch.exit(1)
    await settle()
    await settle()
    expect(kinds(events, "taskEnd").map((e) => e.status)).toEqual(["failed"])
    for (const c of composers()) {
      expect(c.cancelled).toHaveLength(1)
      expect(procs.sent().filter(([t, s]) => t === -c.pid && s === "SIGKILL")).toHaveLength(1)
    }
    await vi.advanceTimersByTimeAsync(3000)
    for (const c of composers()) expect(procs.sent().filter(([t, s]) => t === -c.pid && s === "SIGKILL")).toHaveLength(1)
    expect(events.findIndex((e) => e.kind === "data" && "taskEnd" in e.payload)).toBeLessThan(events.findIndex((e) => e.kind === "end"))
  })

  it("the settle timeout ends the task cancelled at once; later answers emit nothing; the 1 s SIGKILL still runs", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
    const { events, composers } = await compose("v3", [["a"]])
    const [c1] = composers()
    c1.silent.add("session/prompt")
    c1.surviveTerm = true
    acp.cancelSession("C1")
    await vi.advanceTimersByTimeAsync(1000)
    await settle()
    expect(procs.sent()).toContainEqual([-c1.pid, "SIGKILL"])
    await vi.advanceTimersByTimeAsync(5000)
    await settle()
    expect(kinds(events, "taskEnd").map((e) => e.status)).toEqual(["cancelled"])
    const count = events.length
    c1.update(sid(c1), { sessionUpdate: "tool_call", toolCallId: "late", title: "@sdpm/run_python", rawInput: { tool_id: "sdpm::run_python", arguments: {} }, _meta: { kiro: { serverName: "sdpm" } } })
    await settle()
    expect(events.length).toBe(count)
  })

  it("the chat's kiro-cli exit SIGKILLs every composer tree at once and keeps the failed report for the next message", async () => {
    const { events, orch, composers } = await compose("v3", [["a"], ["b"]])
    orch.exit(1)
    await settle()
    await settle()
    for (const c of composers()) expect(procs.sent()).toContainEqual([-c.pid, "SIGKILL"])
    const ends = kinds(events, "taskEnd")
    expect(ends.map((e) => e.status)).toEqual(["failed"])
    expect(events.findIndex((e) => e.kind === "data" && "taskEnd" in e.payload)).toBeLessThan(events.findIndex((e) => e.kind === "end"))
    setEngine("v3")
    await acp.createNewProcessFor("C1")
    const next = await acp.sendPrompt("C1", "still there?")
    next.send()
    await settle()
    expect(prompts(children.at(-1)!).at(-1)).toMatch(/^<compose_result task="0123456789ab" status="failed">/)
  })
})

describe("queue and timeout", () => {
  it("runs a second dispatch after the first ends", async () => {
    const { orch, events, composers } = await compose("v3", [["a"]], { keepTurn: true })
    callTool(orch, "v3", "disp2", "compose_slides", {}, dispatched([["b"]], "00000000000b"))
    await settle()
    expect(kinds(events, "taskStart").map((t) => t.taskId)).toEqual(["0123456789ab", "00000000000b"])
    expect(composers()).toHaveLength(1)
    orch.endTurn("end_turn", "K1")
    composers()[0].endTurn()
    await settle()
    await settle()
    expect(composers()).toHaveLength(2)
    expect(prompts(composers()[1])[0]).toContain("assigned_slugs: b")
  })

  it("fails the task after 60 minutes: composers cancelled, SIGKILL 1 s later, the orchestrator woken", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
    const { events, orch, composers } = await compose("v3", [["a"]])
    const [c1] = composers()
    await vi.advanceTimersByTimeAsync(3_600_000)
    expect(c1.cancelled).toEqual([sid(c1)])
    c1.endTurn("cancelled")
    await settle()
    const end = kinds(events, "taskEnd")[0]
    expect(end.status).toBe("failed")
    expect(JSON.parse(end.content as string).failed_groups[0].error).toBe("timed out after 60 minutes")
    expect(prompts(orch).at(-1)).toMatch(/^<compose_result task="0123456789ab" status="failed">/)
  })
})

describe("a closed tab", () => {
  it("replays a compose period once after the cap released its chat; the next /stream finds nothing", async () => {
    const { orch, composers } = await compose("v3", [["a"]])
    composers()[0].endTurn()
    await settle()
    orch.update("K1", { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "Report seen." } })
    orch.endTurn("end_turn", "K1")
    await settle()
    for (let i = 2; i <= 4; i++) await acp.createNewProcessFor(`L${i}`)
    await settle()
    expect(orch.killed).toBe(true)
    const stream = async (id: string) => {
      const opened = acp.openStream(id)
      if (!opened) return null
      const { createSSEStream } = await import("./sse-bridge")
      const text = await new Response(createSSEStream(opened)).text()
      return text.split("\n\n").filter(Boolean).map((block) => JSON.parse(block.split("\n").find((l) => l.startsWith("data: "))!.slice(6)))
    }
    const replayed = await stream("C1")
    expect(replayed?.some((p) => "taskStart" in p)).toBe(true)
    expect(replayed?.some((p) => "taskEnd" in p)).toBe(true)
    expect(replayed?.map((p) => p.event?.contentBlockDelta?.delta?.text).filter(Boolean)).toEqual(["Report seen."])
    expect(await stream("C1")).toBeNull()
  })
})
