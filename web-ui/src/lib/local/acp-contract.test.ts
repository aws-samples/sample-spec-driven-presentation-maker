// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Contract tests: kiro-cli 3.0.0's own output (src/test/fixtures/acp, V2 and V3) replayed
 * through the ACP process manager and the SSE bridge. What must hold on either engine: the
 * main session's text arrives in order, the stream closes when session/prompt is answered,
 * whatever stopReason it carries, and closes with an error when kiro-cli dies mid-turn.
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
const ENGINES = {
  v2: path.join(FIXTURES, "kiro-3.0.0-v2-turn.jsonl"),
  v3: path.join(FIXTURES, "kiro-3.0.0-v3-turn.jsonl"),
} as const

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

/** SSE `data:` payloads of a stream, read to its end. */
async function readEvents(stream: ReadableStream): Promise<Line[]> {
  const text = await new Response(stream).text()
  return text.split("\n\n").filter(Boolean).map((block) => JSON.parse(block.split("\n").find((l) => l.startsWith("data: "))!.slice(6)))
}

/** The main session's agent_message_chunk text, in capture order. */
function capturedText(lines: Line[], sessionId: string): string {
  return lines
    .filter((m) => m.method === "session/update")
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

async function runTurn(engine: keyof typeof ENGINES, setup: (child: ReplayChild) => void = () => {}) {
  const lines = readFixture(ENGINES[engine])
  spawn.mockImplementation(() => {
    const child = new ReplayChild(lines)
    setup(child)
    children.push(child)
    return child
  })
  const ps = await acp.createNewProcessFor("C1")
  const prompted = await acp.sendPrompt("C1", "Call the sdpm list_styles tool once, then reply with only the number of styles.")
  const onError = vi.fn()
  const stream = bridge.createSSEStream({ sessionId: prompted.sessionId, subscribe: prompted.subscribe, onError })
  prompted.send()
  const events = await readEvents(stream)
  return { lines, sessionId: ps.sessionId!, events, onError }
}

describe.each(Object.keys(ENGINES) as (keyof typeof ENGINES)[])("kiro-cli 3.0.0 %s", (engine) => {
  it("streams the main session's text and closes when session/prompt is answered", async () => {
    const { lines, sessionId, events, onError } = await runTurn(engine)
    const expected = capturedText(lines, sessionId)
    expect(expected).not.toBe("")
    expect(textOf(events)).toBe(expected)
    expect(events.some((e) => e.status === "error")).toBe(false)
    expect(onError).not.toHaveBeenCalled()
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
    const { events, onError } = await runTurn(engine, (child) => { child.stopPromptAfter = 3 })
    expect(events.at(-1)).toMatchObject({ status: "error", code: "agent_exited" })
    expect(onError).toHaveBeenCalledOnce()
    expect(acp.hasProcess("C1")).toBe(false)
  })
})
