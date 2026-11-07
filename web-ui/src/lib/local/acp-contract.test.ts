// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Contract tests: kiro-cli 3.0.0's own output (src/test/fixtures/acp) replayed through the ACP
 * process manager, on the engine adapter the capture's engine needs, and the SSE bridge.
 *
 * - A turn: the main session's text arrives in order, the stream closes when session/prompt is
 *   answered, whatever stopReason it carries, and closes with an error when kiro-cli dies mid-turn.
 * - V2 delegating to the composer: only the main session's text reaches the chat, the composer's
 *   tool chunks make no cards of their own, the delegation is one Compose card that finishes,
 *   and the stream's ids are the buffer's, so a reconnect replays nothing twice.
 * - The same delegation on V2 and V3 streams a Compose card of the same shape (tool names, one
 *   card, its groups and how each ended, closed).
 * - V3 delegating: only the main session's text (no thoughts, nothing from a sub-agent) reaches
 *   the chat; Tool Load and Subagent Response make no cards; the delegation to the composer opens
 *   the Compose card and its end closes it; two delegations in parallel are one card with two
 *   groups, both done; a delegation to another agent is one plain card; a tool update with no
 *   call before it still gets its card.
 * - Start-up: a session is ready once its sdpm server is (V2 reports it before its answers, so
 *   the wait ends at once; V3 after, so it waits); a failed sdpm server, another mode and a
 *   missing sign-in fail the start; a load tells resumed from created; a loaded session in
 *   another mode is switched and waited for again; a sub-agent session's MCP state does not
 *   count for the main one. V3's permission requests are answered with its allow_once option.
 */

import { EventEmitter } from "events"
import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn() }))

type Line = Record<string, unknown>
type Engine = "v2" | "v3"

const FIXTURES = path.resolve(__dirname, "../../test/fixtures/acp")
const fixture = (name: string) => path.resolve(FIXTURES, `kiro-3.0.0-${name}.jsonl`) // nosemgrep: path-join-resolve-traversal — constant fixture names
const TURNS: Record<string, { engine: Engine; file: string }> = {
  V2: { engine: "v2", file: fixture("v2-turn") },
  V3: { engine: "v3", file: fixture("v3-turn") },
}
const V2_COMPOSE_MAIN = "fa1545df-a090-4aa9-bc0e-a6331b67c396"
const V2_COMPOSE_CHILD = "621f8fd1-7983-4c2c-a454-5013b49d38a9"

function readFixture(fixturePath: string): Line[] {
  return fs.readFileSync(fixturePath, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
}

const isResponse = (m: Line) => m.id != null && m.method === undefined
/** `{"client": {id, method}}`: where the capturing client sent a request (README). */
const marker = (m: Line) => m.client as { id: number; method: string } | undefined

/**
 * Plays a captured kiro-cli: each request is matched with the capture's next client request
 * (same method, else the test fails) and answered with the lines the capture had from there to
 * the next client request, the answer's id rewritten to this request's. Lines that followed the
 * answer before the capturing client's next request (V3's MCP readiness) come with it.
 */
class ReplayChild extends EventEmitter {
  pid = 4242
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin = Object.assign(new EventEmitter(), { write: (line: string) => { this.handle(JSON.parse(line)); return true } })
  killed = false
  /** Lines this client wrote that were answers to kiro-cli's requests. */
  answers: Line[] = []
  /** The methods of the requests this client sent, in order. */
  requests: string[] = []
  private cursor = 0
  /** Stop before the prompt's answer (after this many of its lines) to model a crash. */
  stopPromptAfter: number | null = null
  /** Replace the prompt's stopReason. */
  stopReason: string | null = null
  constructor(private readonly lines: Line[]) { super() }

  private handle(req: Line) {
    if (req.method === undefined) { this.answers.push(req); return }
    if (req.id == null) return
    this.requests.push(req.method as string)
    const at = this.lines.findIndex((line, i) => i >= this.cursor && marker(line))
    const expected = at >= 0 ? marker(this.lines[at])! : null
    if (!expected || expected.method !== req.method) {
      throw new Error(`the capture's next request is ${expected?.method ?? "none"}, the client sent ${req.method}`)
    }
    const next = this.lines.findIndex((line, i) => i > at && marker(line))
    this.cursor = next < 0 ? this.lines.length : next
    const out = this.lines.slice(at + 1, this.cursor).map((line) => {
      if (!isResponse(line) || line.id !== expected.id) return line
      return { ...line, id: req.id, ...(this.stopReason && req.method === "session/prompt" ? { result: { stopReason: this.stopReason } } : {}) }
    })
    const lines = req.method === "session/prompt" && this.stopPromptAfter != null ? out.slice(0, this.stopPromptAfter) : out
    setImmediate(() => { if (lines.length) this.stdout.emit("data", lines.map((l) => JSON.stringify(l)).join("\n") + "\n") })
    if (lines !== out) setImmediate(() => this.kill())
  }

  kill() {
    if (!this.killed) {
      this.killed = true
      setImmediate(() => this.emit("close", null))
    }
    return true
  }
}

/** SSE `id:` and `data:` of each event of a stream, read to its end. */
async function readBlocks(stream: ReadableStream): Promise<{ id: number; data: Line }[]> {
  const text = await new Response(stream).text()
  return text.split("\n\n").filter(Boolean).map((block) => {
    const lines = block.split("\n")
    return { id: Number(lines.find((l) => l.startsWith("id: "))!.slice(4)), data: JSON.parse(lines.find((l) => l.startsWith("data: "))!.slice(6)) }
  })
}

type Update = { sessionUpdate: string; content?: { text?: string }; _meta?: { kiro?: { agentSubtaskId?: string; replay?: boolean } } }

/** The main session's agent_message_chunk text, in capture order: no sub-agent's (V3) and no replay. */
function capturedText(lines: Line[], sessionId: string): string {
  return lines
    .filter((m) => m.method === "session/update" || m.method === "_kiro.dev/session/update")
    .map((m) => m.params as { sessionId: string; update: Update })
    .filter((p) => p.sessionId === sessionId && p.update.sessionUpdate === "agent_message_chunk")
    .filter((p) => !p.update._meta?.kiro?.agentSubtaskId && !p.update._meta?.kiro?.replay)
    .map((p) => p.update.content?.text ?? "")
    .join("")
}

const textOf = (events: Line[]) => events
  .map((e) => ((e.event as { contentBlockDelta?: { delta?: { text?: string } } } | undefined)?.contentBlockDelta?.delta?.text) ?? "")
  .join("")

/** The names of the cards a stream opened (toolStart / toolUse). */
const cardNames = (events: Line[]) => events.flatMap((e) => [e.toolStart, e.toolUse].filter(Boolean)).map((t) => (t as { name: string }).name)

/** The Compose card's stream events (`toolStream` data). */
const streamedOf = (events: Line[]) => events.flatMap((e) => (e.toolStream ? [(e.toolStream as { data: Line }).data] : []))

/** The statuses the Compose card closed with (`toolResult compose_slides`). */
const composeResults = (events: Line[]) => events
  .map((e) => e.toolResult as { name?: string; status?: string } | undefined)
  .filter((r) => r?.name === "compose_slides")
  .map((r) => r!.status)

/**
 * What a stream's Compose card looks like, without ids or text: the card names in order (V2's
 * toolStart and toolUse of one call count once), the `toolUse compose_slides` count, the number of
 * groups, each group's end states, and the statuses the card closed with.
 */
function composeShape(events: Line[]) {
  const names = cardNames(events).filter((name, i, all) => name !== all[i - 1])
  const streamed = streamedOf(events)
  const groups = [...new Set(streamed.map((d) => d.group))]
  return {
    names,
    uses: events.filter((e) => (e.toolUse as { name?: string } | undefined)?.name === "compose_slides").length,
    groups: groups.length,
    ends: groups.map((g) => streamed.filter((d) => d.group === g && (d.status === "done" || d.status === "error")).map((d) => d.status)),
    results: composeResults(events),
  }
}

let children: ReplayChild[]
let acp: typeof import("./acp-process")
let bridge: typeof import("./sse-bridge")
let configDir: string

beforeEach(async () => {
  children = []
  spawn.mockReset()
  configDir = fs.mkdtempSync(path.resolve(os.tmpdir(), "sdpm-acp-contract-"))
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", configDir)
  vi.resetModules()
  acp = await import("./acp-process")
  bridge = await import("./sse-bridge")
})

afterEach(() => {
  for (const child of children) child.kill()
  vi.useRealTimers()
  vi.unstubAllEnvs()
  fs.rmSync(configDir, { recursive: true, force: true })
})

/** kiro-cli replays `file` on `engine` (acp-config.json, as Settings writes it). */
function replay(engine: Engine, file: string, setup: (child: ReplayChild) => void = () => {}, edit: (lines: Line[]) => Line[] = (l) => l): Line[] {
  fs.writeFileSync(path.resolve(configDir, "acp-config.json"), JSON.stringify({ version: 2, engine }))
  const lines = edit(readFixture(file))
  spawn.mockImplementation(() => {
    const child = new ReplayChild(lines)
    setup(child)
    children.push(child)
    return child
  })
  return lines
}

/** One prompt on a client's process (C1's by default), its stream read to its end. */
async function prompt(text: string, clientId = "C1") {
  const prompted = await acp.sendPrompt(clientId, text)
  const stream = bridge.createSSEStream({ subscribe: prompted.subscribe, replay: acp.getBufferedEvents(clientId) })
  prompted.send()
  return readBlocks(stream)
}

/** The capture's lines of its n-th client request (from 0), up to the next one. */
function window(lines: Line[], n: number): Line[] {
  const at = lines.flatMap((line, i) => (marker(line) ? [i] : []))
  return lines.slice(at[n] + 1, at[n + 1] ?? lines.length)
}

describe.each(Object.keys(TURNS))("kiro-cli 3.0.0 %s, a turn", (name) => {
  const { engine, file } = TURNS[name]

  async function runTurn(setup: (child: ReplayChild) => void = () => {}) {
    const lines = replay(engine, file, setup)
    const ps = await acp.createNewProcessFor("C1")
    const events = (await prompt("Call the sdpm list_styles tool once, then reply with only the number of styles.")).map((b) => b.data)
    return { lines, sessionId: ps.sessionId!, events }
  }

  it("streams the main session's text and closes when session/prompt is answered", async () => {
    const { lines, sessionId, events } = await runTurn()
    const expected = capturedText(lines, sessionId)
    expect(expected).not.toBe("")
    expect(textOf(events)).toBe(expected)
    expect(events.some((e) => e.status === "error")).toBe(false)
    expect(acp.isSessionRunning("C1")).toBe(false)
  })

  it("streams the turn's tool call and its completion, and no card for kiro-cli's internal calls", async () => {
    const { events } = await runTurn()
    // V2 announces the call (toolStart) before its input (toolUse): one card.
    expect([...new Set(cardNames(events))]).toEqual(["list_styles"])
    const toolUseId = ((events.find((e) => e.toolUse || e.toolStart)!.toolUse || events.find((e) => e.toolStart)!.toolStart) as { toolUseId: string }).toolUseId
    expect(events.filter((e) => e.toolResult).map((e) => (e.toolResult as { toolUseId: string }).toolUseId)).toEqual([toolUseId])
  })

  it.each(["refusal", "max_tokens", "max_turn_requests"])("closes a turn that ends with %s, after its text, with that code", async (stopReason) => {
    const { lines, sessionId, events } = await runTurn((child) => { child.stopReason = stopReason })
    expect(textOf(events)).toBe(capturedText(lines, sessionId))
    expect(events.at(-1)).toMatchObject({ status: "error", code: stopReason })
    expect(acp.isSessionRunning("C1")).toBe(false)
  })

  it("closes with agent_exited when kiro-cli dies mid-turn, and the session is free again", async () => {
    const { events } = await runTurn((child) => { child.stopPromptAfter = 3 })
    expect(events.at(-1)).toMatchObject({ status: "error", code: "agent_exited" })
    expect(acp.hasProcess("C1")).toBe(false)
  })
})

describe("kiro-cli 3.0.0 V2, a turn that delegates to the composer", () => {
  async function runCompose() {
    const lines = replay("v2", fixture("v2-compose"))
    await acp.createNewProcessFor("C1")
    const first = await prompt("Call the sdpm list_styles tool once, then reply with only the number of styles.")
    const second = await prompt("Delegate to the sdpm-composer sub-agent.")
    return { lines, first, second }
  }

  it("streams only the main session's text, none of the composer's", async () => {
    const { lines, first, second } = await runCompose()
    const turn2 = window(lines, 3)
    expect(textOf(first.map((b) => b.data))).toBe("21")
    expect(textOf(second.map((b) => b.data))).toBe(capturedText(turn2, V2_COMPOSE_MAIN))
    expect(capturedText(turn2, V2_COMPOSE_CHILD)).not.toBe("")
  })

  it("makes no cards of the composer's tool chunks, and one Compose card of the delegation", async () => {
    const { second } = await runCompose()
    const events = second.map((b) => b.data)
    expect(cardNames(events)).toEqual(["compose_slides", "compose_slides"])
    expect(streamedOf(events).map((d) => d.status ?? d.tool ?? d.toolStatus)).toEqual(["starting", "list_templates", "success", "Summarizing", "success", "done"])
    expect(composeResults(events)).toEqual(["success"])
  })

  it("numbers the stream's events as the buffer does, so a reconnect replays nothing twice", async () => {
    const { second } = await runCompose()
    const ids = second.map((b) => b.id)
    expect(ids).toEqual(ids.map((_, i) => i + 1))
    // The turn's end is buffered after the last written event.
    expect(acp.getBufferedEvents("C1").map((e) => e.id)).toEqual([...ids, ids.length + 1])
    const lastSeen = ids[4]
    const reconnect = await readBlocks(bridge.createSSEStream({ subscribe: () => () => {}, replay: acp.getBufferedEvents("C1", lastSeen) }))
    expect([...second.slice(0, 5), ...reconnect]).toEqual(second)
  })

  it("keeps the composer session's MCP state apart from the main session's", async () => {
    const lines = readFixture(fixture("v2-compose"))
    const { V2Translator } = await import("./acp/engines/v2/translate")
    const { McpRecord } = await import("./mcp-ready")
    const translator = new V2Translator()
    const record = new McpRecord()
    for (const line of lines.filter((l) => typeof l.method === "string")) {
      for (const event of translator.translate(line as { method: string; params?: unknown })) {
        if (event.type === "mcp_status" || event.type === "mcp_snapshot") record.apply(event)
      }
    }
    expect(record.get(V2_COMPOSE_CHILD, "sdpm")?.state).toBe("connected")
    record.clear(V2_COMPOSE_MAIN)
    expect(record.get(V2_COMPOSE_MAIN, "sdpm")).toBeUndefined()
  })
})

describe("kiro-cli 3.0.0, the same delegation on V2 and V3", () => {
  /** The captures' second turn: the orchestrator delegates one group to the composer. */
  async function delegation(engine: Engine) {
    replay(engine, fixture(`${engine}-compose`))
    await acp.createNewProcessFor("C1")
    await prompt("Call the sdpm list_styles tool once.")
    return (await prompt("Delegate to the sdpm-composer sub-agent.")).map((b) => b.data)
  }

  it("streams the same Compose card shape: tool names, one card, its group and how it ended", async () => {
    const v2 = composeShape(await delegation("v2"))
    const v3 = composeShape(await delegation("v3"))
    expect(v3).toEqual(v2)
    expect(v2).toEqual({ names: ["compose_slides"], uses: 1, groups: 1, ends: [["done"]], results: ["success"] })
  })
})

describe("kiro-cli 3.0.0 V3, turns that delegate", () => {
  const V3_COMPOSE_MAIN = "sess_1841ca0d-7448-4f52-9ced-50f300f95b10"

  it("streams only the main session's text, without thoughts or a sub-agent's, and hides Tool Load and Subagent Response", async () => {
    const lines = replay("v3", fixture("v3-compose"))
    await acp.createNewProcessFor("C1")
    const first = (await prompt("Call the sdpm list_styles tool once.")).map((b) => b.data)
    const second = (await prompt("Delegate to the sdpm-composer sub-agent.")).map((b) => b.data)
    expect(textOf(first)).toBe(capturedText(window(lines, 2), V3_COMPOSE_MAIN))
    expect(textOf(second)).toBe(capturedText(window(lines, 3), V3_COMPOSE_MAIN))
    expect(textOf(second)).not.toContain("Subagent Response")
    // (a) Tool Load (main and sub-agent) and Subagent Response arrive as updates alone; no card.
    expect(cardNames(first)).toEqual(["list_styles"])
    expect([...cardNames(first), ...cardNames(second)]).not.toContain("Tool Load")
    // (b) The delegation carries its own agentSubtaskId and still opens the Compose card.
    expect(cardNames(second)).toEqual(["compose_slides"])
    const delegation = second.find((e) => e.toolUse)!.toolUse as { toolUseId: string; input: { slide_groups: unknown[] } }
    expect(delegation.toolUseId).toMatch(/^invoke_subagent_/)
    expect(delegation.input.slide_groups).toHaveLength(1)
    expect(streamedOf(second).map((d) => d.status ?? d.tool ?? d.toolStatus)).toEqual(["starting", "list_templates", "success", "done"])
    // The delegation's end closes the card.
    expect(second.filter((e) => e.toolResult).map((e) => e.toolResult)).toEqual([
      { toolUseId: delegation.toolUseId, name: "compose_slides", status: "success", content: "{}" },
    ])
  })

  it("keeps a sub-agent's text chunk out of the chat", async () => {
    replay("v3", fixture("v3-compose"), () => {}, (lines) => {
      const turn = lines.findIndex((l, i) => i > 0 && marker(l)?.method === "session/prompt" && lines.slice(0, i).filter((x) => marker(x)?.method === "session/prompt").length === 1)
      const subtask = { method: "session/update", params: { sessionId: V3_COMPOSE_MAIN, update: {
        sessionUpdate: "agent_message_chunk", content: { type: "text", text: "COMPOSER SAYS" }, _meta: { kiro: { agentSubtaskId: "e71abb85-e475-45a9-80bf-ed06520917f2" } },
      } } }
      return [...lines.slice(0, turn + 2), subtask, ...lines.slice(turn + 2)]
    })
    await acp.createNewProcessFor("C1")
    await prompt("Call the sdpm list_styles tool once.")
    expect(textOf((await prompt("Delegate.")).map((b) => b.data))).not.toContain("COMPOSER SAYS")
  })

  it("streams only the main session's text on two delegations in parallel, and shows both as one Compose card that finishes", async () => {
    const lines = replay("v3", fixture("v3-parallel-compose"))
    const ps = await acp.createNewProcessFor("C1")
    const events = (await prompt("Delegate to two sdpm-composer sub-agents in parallel.")).map((b) => b.data)
    expect(textOf(events)).toBe(capturedText(window(lines, 2), ps.sessionId!))
    expect(cardNames(events)).toEqual(["start_presentation", "compose_slides"])
    expect(composeShape(events)).toMatchObject({ uses: 1, groups: 2, ends: [["done"], ["done"]], results: ["success"] })
    const starting = streamedOf(events).filter((d) => d.status === "starting")
    expect(starting.map((d) => [d.group, d.total_groups])).toEqual([[1, 1], [2, 2]])
    // The card closes after both groups are done, under the first delegation's tool call.
    const closed = events.findIndex((e) => e.toolResult && (e.toolResult as { name: string }).name === "compose_slides")
    expect(events.slice(closed + 1).some((e) => e.toolStream)).toBe(false)
    expect((events[closed].toolResult as { toolUseId: string }).toolUseId).toBe((events.find((e) => e.toolUse && (e.toolUse as { name: string }).name === "compose_slides")!.toolUse as { toolUseId: string }).toolUseId)
  })

  it("(c) shows a delegation to another agent as one plain card, without its inner tools", async () => {
    const { V3Translator } = await import("./acp/engines/v3/translate")
    const { ConversationState } = await import("./conversation")
    const lines = readFixture(fixture("v3-load-subtask-style"))
    const translator = new V3Translator()
    translator.mainSessionId = "642f9579-bce4-4731-803b-10a14e6af289"
    const conversation = new ConversationState()
    const events = lines.filter((l) => l.method === "session/update").flatMap((l) => {
      const local = translator.translate(l as { method: string; params?: unknown }).filter((e) => e.type !== "mcp_status" && e.type !== "mcp_snapshot")
      return conversation.apply(local).events.map((e) => e.payload as Line)
    })
    expect(cardNames(events)).toEqual(["sdpm-style"])
    expect(events.filter((e) => e.toolResult).map((e) => (e.toolResult as { name: string; status: string }))).toMatchObject([{ name: "sdpm-style", status: "success" }])
    expect(events.some((e) => e.toolStream)).toBe(false)
  })

  it("(d) gives a tool that only an update announced its card before the result", async () => {
    replay("v3", fixture("v3-turn"), () => {}, (lines) => lines.filter((l) => {
      const update = (l.params as { update?: { sessionUpdate?: string } } | undefined)?.update
      return update?.sessionUpdate !== "tool_call"
    }))
    await acp.createNewProcessFor("C1")
    const events = (await prompt("Call the sdpm list_styles tool once.")).map((b) => b.data)
    expect(cardNames(events)).toEqual(["list_styles"])
    const use = events.findIndex((e) => e.toolUse)
    const result = events.findIndex((e) => e.toolResult)
    expect(use).toBeGreaterThanOrEqual(0)
    expect(result).toBeGreaterThan(use)
  })

  it("answers V3's permission requests with its allow_once option, and shows a tool that failed as failed", async () => {
    replay("v3", fixture("v3-permission"))
    await acp.createNewProcessFor("C1")
    await prompt("Call the sdpm list_styles tool once.")
    const second = (await prompt("Call the sdpm list_styles tool once.")).map((b) => b.data)
    expect(children[0].answers.map((a) => (a.result as { outcome: unknown }).outcome)).toEqual([
      { outcome: "selected", optionId: "accept" }, { outcome: "selected", optionId: "accept" },
    ])
    const failed = second.find((e) => e.toolResult)!.toolResult as { status: string; content: string }
    expect(failed.status).toBe("error")
    expect(JSON.parse(failed.content)).toEqual({ message: "The user rejected this tool call." })
  })
})

describe("kiro-cli 3.0.0 start-up", () => {
  /** The V2 session V3 imports in v3-load-imported, and the session v3-load-setmode loads. */
  const IMPORTED = "52ba6221-a318-4df8-b72a-4696f6e8131a"
  const SETMODE_LOADED = "993d5c85-48c6-4eec-b35d-f5bb96934b81"

  it("V2: the sdpm server reported before session/new's answer ends the wait at once", async () => {
    replay("v2", fixture("v2-new-mcp-first"))
    const started = Date.now()
    await acp.createNewProcessFor("C1")
    expect(Date.now() - started).toBeLessThan(1000)
    expect(acp.hasProcess("C1")).toBe(true)
  })

  it.each([["v2", "v2-mcp-failed"], ["v3", "v3-mcp-failed"]] as const)("%s: a failed sdpm server fails the start with mcp_failed", async (engine, name) => {
    replay(engine, fixture(name))
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      expect(await acp.createNewProcessFor("C1").catch((e: unknown) => e)).toMatchObject({ code: "mcp_failed" })
      expect(children[0].killed).toBe(true)
      expect(acp.hasProcess("C1")).toBe(false)
    } finally {
      warn.mockRestore()
    }
  })

  it.each([["v2", "v2-agent-not-found"], ["v3", "v3-vibe-fallback"]] as const)("%s: another agent than the requested one fails the start with agent_definition_rejected", async (engine, name) => {
    replay(engine, fixture(name))
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      expect(await acp.createNewProcessFor("C1").catch((e: unknown) => e)).toMatchObject({ code: "agent_definition_rejected" })
      expect(acp.hasProcess("C1")).toBe(false)
      expect(warn.mock.calls.flat().join(" ")).toMatch(/did not (find|start)/)
    } finally {
      warn.mockRestore()
    }
  })

  it("V3: not signed in fails the start with agent_auth_required", async () => {
    replay("v3", fixture("v3-auth-required"))
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      expect(await acp.createNewProcessFor("C1").catch((e: unknown) => e)).toMatchObject({ code: "agent_auth_required" })
    } finally {
      warn.mockRestore()
    }
  })

  it("V2: a load kiro-cli answers Session not found continues in the new session, ready at once", async () => {
    replay("v2", fixture("v2-load-not-found"))
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const started = Date.now()
      const { ps, outcome } = await acp.openDeckSession("C1", "d1", "sess_53fd2ae9-a657-4048-97da-38fb5cfed6df", "sdpm-orchestrator")
      expect(Date.now() - started).toBeLessThan(1000)
      expect(outcome).toBe("created")
      expect(ps.sessionId).toBe("7f36556f-6963-42df-9224-6ff45a7a85ce")
      expect(children[0].requests).toEqual(["initialize", "session/new", "session/load"])
    } finally {
      warn.mockRestore()
    }
  })

  it("V3: loading a V2 session it imports is resumed; its replay is counted, not shown", async () => {
    const lines = replay("v3", fixture("v3-load-imported"))
    const phases: unknown[] = []
    const { outcome } = await acp.openForkedSession(IMPORTED, "sdpm-orchestrator", { onPhase: (phase, detail) => { phases.push({ phase, ...detail }) } })
    expect(outcome).toBe("resumed")
    expect(children[0].requests).toEqual(["initialize", "session/load"])
    const replayed = window(lines, 1).filter((l) => ((l.params as { update?: Update } | undefined)?.update?._meta?.kiro?.replay)).length
    expect(replayed).toBeGreaterThan(1)
    expect(phases.at(-1)).toEqual({ phase: "loading", replayed })
    expect(capturedText(window(lines, 1), IMPORTED)).toBe("")
    const events = (await prompt("What was the codeword?", IMPORTED)).map((b) => b.data)
    expect(textOf(events)).toBe("PAPAYA")
  })

  it("V3: a load of a session V3 does not have is created", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(Date.parse("2026-11-05T15:40:29.870Z"))
    replay("v3", fixture("v3-load-created"))
    const info = vi.spyOn(console, "info").mockImplementation(() => {})
    try {
      const { ps, outcome } = await acp.openDeckSession("C1", "d1", "11111111-2222-4333-8444-555555555555", "sdpm-orchestrator")
      expect(outcome).toBe("created")
      expect(ps.sessionId).toBe("11111111-2222-4333-8444-555555555555")
    } finally {
      info.mockRestore()
    }
  })

  it.each([
    ["v2", "v2-setmode-mcp", "2e18976d-24bb-409e-9d75-7359a25296e6"],
    ["v3", "v3-setmode-mcp", "sess_ff4c3912-a8ed-49c2-8c39-6ab43cbbafce"],
    ["v3", "v3-load-setmode", SETMODE_LOADED],
  ] as const)(
    "%s (%s): a loaded session in another mode is switched, and the start waits for the new mode's sdpm server",
    async (engine, name, sessionId) => {
      replay(engine, fixture(name))
      const phases: string[] = []
      const { outcome } = await acp.openForkedSession(sessionId, "sdpm-orchestrator", { onPhase: (phase) => { phases.push(phase) } })
      expect(outcome).toBe("resumed")
      expect(children[0].requests.at(-1)).toBe("session/set_mode")
      expect(phases).toContain("switching")
      expect(acp.hasProcess(sessionId)).toBe(true)
    },
  )

  it("V3 (v3-load-setmode): the switched session answers its turns", async () => {
    const lines = replay("v3", fixture("v3-load-setmode"))
    await acp.openForkedSession(SETMODE_LOADED, "sdpm-orchestrator")
    const first = (await prompt("What was the codeword?", SETMODE_LOADED)).map((b) => b.data)
    expect(textOf(first)).toBe(capturedText(window(lines, 3), SETMODE_LOADED))
    const second = (await prompt("Call the sdpm list_styles tool once.", SETMODE_LOADED)).map((b) => b.data)
    expect(cardNames(second)).toEqual(["list_styles"])
  })
})
