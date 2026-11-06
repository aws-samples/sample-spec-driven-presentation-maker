// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Contract tests: kiro-cli 3.0.0's own output (src/test/fixtures/acp) replayed through the ACP
 * process manager (with the V2 engine adapter) and the SSE bridge. What must hold: the main
 * session's text arrives in order, the stream closes when session/prompt is answered, whatever
 * stopReason it carries, and closes with an error when kiro-cli dies mid-turn. On a V2 turn that
 * delegates to the composer, only the main session's text reaches the chat, the composer's tool
 * chunks make no cards of their own, the delegation is one Compose card, and the stream's ids
 * are the buffer's, so a reconnect replays nothing twice.
 */

import { EventEmitter } from "events"
import fs from "fs"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))
vi.mock("./agents-sync", () => ({ syncToAgentsDir: vi.fn() }))
vi.mock("./acp-adapter", () => ({
  getActiveAgent: () => ({ id: "kiro", path: "kiro-cli", args: ["acp", "--agent", "sdpm-orchestrator"], env: {} }),
}))

type Line = Record<string, unknown>

const FIXTURES = path.resolve(__dirname, "../../test/fixtures/acp")
const TURNS = {
  "V2": path.resolve(FIXTURES, "kiro-3.0.0-v2-turn.jsonl"),
  // The V3 lines through the V2 adapter: replaced by the V3 adapter's contract tests in PR 2-2.
  "V3 lines through the V2 adapter": path.resolve(FIXTURES, "kiro-3.0.0-v3-turn.jsonl"),
} as const
const V2_COMPOSE = path.resolve(FIXTURES, "kiro-3.0.0-v2-compose.jsonl")
const V2_COMPOSE_MAIN = "fa1545df-a090-4aa9-bc0e-a6331b67c396"

function readFixture(fixturePath: string): Line[] {
  return fs.readFileSync(fixturePath, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
}

const isResponse = (m: Line) => m.id != null && m.method === undefined

/**
 * Plays a captured kiro-cli: each request with an id is answered with the capture's next
 * response (id rewritten to the request's), preceded by every line the capture had before it.
 */
class ReplayChild extends EventEmitter {
  pid = 4242
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin = Object.assign(new EventEmitter(), { write: (line: string) => { this.handle(JSON.parse(line)); return true } })
  killed = false
  /** Lines this client wrote that were answers to kiro-cli's requests. */
  answers: Line[] = []
  private cursor = 0
  /** Stop before the prompt's answer (after this many of its lines) to model a crash. */
  stopPromptAfter: number | null = null
  /** Replace the prompt's stopReason. */
  stopReason: string | null = null
  constructor(private readonly lines: Line[]) { super() }

  private handle(req: Line) {
    if (req.method === undefined) { this.answers.push(req); return }
    if (req.id == null) return
    const out: Line[] = []
    while (this.cursor < this.lines.length) {
      const line = this.lines[this.cursor++]
      if (isResponse(line)) {
        out.push({ ...line, id: req.id, ...(this.stopReason && req.method === "session/prompt" ? { result: { stopReason: this.stopReason } } : {}) })
        break
      }
      out.push(line)
    }
    const lines = req.method === "session/prompt" && this.stopPromptAfter != null ? out.slice(0, this.stopPromptAfter) : out
    setImmediate(() => this.stdout.emit("data", lines.map((l) => JSON.stringify(l)).join("\n") + "\n"))
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


/** The main session's agent_message_chunk text, in capture order. */
function capturedText(lines: Line[], sessionId: string): string {
  return lines
    .filter((m) => m.method === "session/update" || m.method === "_kiro.dev/session/update")
    .map((m) => m.params as { sessionId: string; update: { sessionUpdate: string; content?: { text?: string } } })
    .filter((p) => p.sessionId === sessionId && p.update.sessionUpdate === "agent_message_chunk")
    .map((p) => p.update.content?.text ?? "")
    .join("")
}

const textOf = (events: Line[]) => events
  .map((e) => ((e.event as { contentBlockDelta?: { delta?: { text?: string } } } | undefined)?.contentBlockDelta?.delta?.text) ?? "")
  .join("")

let children: ReplayChild[]
let acp: typeof import("./acp-process")
let bridge: typeof import("./sse-bridge")

beforeEach(async () => {
  children = []
  spawn.mockReset()
  vi.resetModules()
  acp = await import("./acp-process")
  bridge = await import("./sse-bridge")
})

afterEach(() => {
  for (const child of children) child.kill()
})

function replay(fixture: string, setup: (child: ReplayChild) => void = () => {}): Line[] {
  const lines = readFixture(fixture)
  spawn.mockImplementation(() => {
    const child = new ReplayChild(lines)
    setup(child)
    children.push(child)
    return child
  })
  return lines
}

/** One prompt on C1's process, its stream read to its end. */
async function prompt(text: string) {
  const prompted = await acp.sendPrompt("C1", text)
  const stream = bridge.createSSEStream({ subscribe: prompted.subscribe, replay: acp.getBufferedEvents("C1") })
  prompted.send()
  return readBlocks(stream)
}

async function runTurn(engine: keyof typeof TURNS, setup: (child: ReplayChild) => void = () => {}) {
  const lines = replay(TURNS[engine], setup)
  const ps = await acp.createNewProcessFor("C1")
  const events = (await prompt("Call the sdpm list_styles tool once, then reply with only the number of styles.")).map((b) => b.data)
  return { lines, sessionId: ps.sessionId!, events }
}

describe.each(Object.keys(TURNS) as (keyof typeof TURNS)[])("kiro-cli 3.0.0 %s", (engine) => {
  it("streams the main session's text and closes when session/prompt is answered", async () => {
    const { lines, sessionId, events } = await runTurn(engine)
    const expected = capturedText(lines, sessionId)
    expect(expected).not.toBe("")
    expect(textOf(events)).toBe(expected)
    expect(events.some((e) => e.status === "error")).toBe(false)
    expect(acp.isSessionRunning("C1")).toBe(false)
  })

  it("streams the turn's tool call and its completion", async () => {
    const { events } = await runTurn(engine)
    const started = events.find((e) => e.toolUse || e.toolStart)
    expect(started).toBeDefined()
    const toolUseId = ((started!.toolUse || started!.toolStart) as { toolUseId: string }).toolUseId
    expect(events.some((e) => (e.toolResult as { toolUseId?: string } | undefined)?.toolUseId === toolUseId)).toBe(true)
  })

  it.each(["refusal", "max_tokens", "max_turn_requests"])("closes a turn that ends with %s, after its text, with that code", async (stopReason) => {
    const { lines, sessionId, events } = await runTurn(engine, (child) => { child.stopReason = stopReason })
    expect(textOf(events)).toBe(capturedText(lines, sessionId))
    expect(events.at(-1)).toMatchObject({ status: "error", code: stopReason })
    expect(acp.isSessionRunning("C1")).toBe(false)
  })

  it("closes with agent_exited when kiro-cli dies mid-turn, and the session is free again", async () => {
    const { events } = await runTurn(engine, (child) => { child.stopPromptAfter = 3 })
    expect(events.at(-1)).toMatchObject({ status: "error", code: "agent_exited" })
    expect(acp.hasProcess("C1")).toBe(false)
  })
})

/** The capture's lines of its second prompt (the delegation), up to that prompt's answer. */
function secondTurn(lines: Line[]): Line[] {
  const answers = lines.flatMap((line, i) => (isResponse(line) ? [i] : []))
  return lines.slice(answers[2] + 1, answers[3] + 1)
}

describe("kiro-cli 3.0.0 V2, a turn that delegates to the composer", () => {
  async function runCompose() {
    const lines = replay(V2_COMPOSE)
    await acp.createNewProcessFor("C1")
    const first = await prompt("Call the sdpm list_styles tool once, then reply with only the number of styles.")
    const second = await prompt("Delegate to the sdpm-composer sub-agent.")
    return { lines, first, second }
  }

  it("streams only the main session's text, none of the composer's", async () => {
    const { lines, first, second } = await runCompose()
    const turn2 = secondTurn(lines)
    expect(textOf(first.map((b) => b.data))).toBe("21")
    expect(textOf(second.map((b) => b.data))).toBe(capturedText(turn2, V2_COMPOSE_MAIN))
    expect(capturedText(turn2, "621f8fd1-7983-4c2c-a454-5013b49d38a9")).not.toBe("")
  })

  it("makes no cards of the composer's tool chunks, and one Compose card of the delegation", async () => {
    const { second } = await runCompose()
    const events = second.map((b) => b.data)
    const cardNames = events.flatMap((e) => [e.toolStart, e.toolUse].filter(Boolean)).map((t) => (t as { name: string }).name)
    expect(cardNames).toEqual(["compose_slides", "compose_slides"])
    const streamed = events.flatMap((e) => (e.toolStream ? [(e.toolStream as { data: Line }).data] : []))
    expect(streamed.map((d) => d.status ?? d.tool ?? d.toolStatus)).toEqual(["starting", "list_templates", "success", "Summarizing", "success"])
    expect(events.filter((e) => (e.toolResult as { name?: string } | undefined)?.name === "compose_slides")).toHaveLength(1)
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
})
