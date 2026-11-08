// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A fake kiro-cli child process for the Local ACP tests (hosts, chats, the registry): it answers
 * the ACP requests the client sends on its stdin, on V2 (`acp --agent <name>`) or V3
 * (`acp --agent-engine v3`), and carries any number of sessions.
 *
 * - `session/new` gives each session its own id: the child's first is the id it was made with
 *   (`K1`), the next ones `K1-2`, `K1-3`, … Each session keeps its own model and effort.
 * - V3's initialize advertises `sessionCapabilities {list, close, delete, fork}`; V2's none.
 * - `session/close` and `session/delete` are recorded (`closed`, `deleted`) and answered.
 * - `prompts` holds the unanswered session/prompt requests; `endTurn` / `failPrompt` answer the
 *   oldest one of a session (default: the oldest of all).
 * - The sdpm server's state is sent before the answer that opens a session (as V2 does).
 * - Each child has a pid of its own, above any real pid limit (Linux 4 194 304, macOS 99 998), so
 *   a signal that reached the real `process.kill` could only fail. `pgid`, `descendants` and
 *   `surviveTerm` describe its process tree to `installFakeProcesses` (fakeProcesses.ts).
 */

import { EventEmitter } from "events"

export type Rpc = { id: number; method: string; params: Record<string, unknown> }

/** The fake kiro-cli's models: `m-effort` has effort levels (V3 only). */
export const FAKE_MODELS = ["auto", "m-effort", "m-plain"]

let lastFakePid = 5_000_000
/** A pid no real process can have. */
export const nextFakePid = () => ++lastFakePid

/** A process below a fake kiro-cli (V3's agent server, V2's MCP servers) in the fake process table. */
export interface FakeDescendant {
  pid: number
  pgid: number
  ppid: number
  /** Ended by a signal to its group or pid. */
  dead?: boolean
}

export class FakeChild extends EventEmitter {
  pid = nextFakePid()
  /** Its process group (default: its own when spawned detached, else the Local server's). */
  pgid: number | undefined = undefined
  /** Fake processes below it, listed while alive. */
  descendants: FakeDescendant[] = []
  /** Its descendants live on after SIGTERM (only SIGKILL ends them). */
  surviveTerm = false
  /** It exited on its own (`exit`). */
  exited = false
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin = Object.assign(new EventEmitter(), { write: (line: string) => { this.handle(JSON.parse(line)); return true } })
  killed = false
  /** Unanswered session/prompt requests, oldest first. */
  prompts: { id: number; sessionId: string }[] = []
  cancelled: string[] = []
  /** Sessions ended with session/close, and deleted with session/delete. */
  closed: string[] = []
  deleted: string[] = []
  /** What this client wrote back for kiro-cli's own requests. */
  answers: Record<string, unknown>[] = []
  /** Methods answered with a JSON-RPC error instead of a result. */
  failing = new Set<string>()
  /** Methods never answered (a kiro-cli that hangs). */
  silent = new Set<string>()
  /** Every request this client sent, in order. */
  requests: Rpc[] = []
  /** The answer to `_session/steer` (V2 shape; V3 adds a messageId). */
  steerAnswer: Record<string, unknown> = { queued: true }
  /** Sessions kiro-cli does not have: V2 answers their load with Session not found, V3 creates them empty. */
  missing = new Set<string>()
  /** The mode a loaded session is in (default: the requested agent's). */
  loadedMode: string | null = null
  /** The mode session/new answers (default: the requested agent's). */
  newMode: string | null = null
  /** The sdpm server's state kiro-cli reports for each session it opens (`none`: nothing yet). */
  mcpState: "connected" | "failed" | "none" = "connected"
  /** Forks made with session/fork (V3), by id: their source. */
  forks = new Map<string, string>()
  /** Each session's model and effort (set_config_option / set_model change them). */
  readonly configs = new Map<string, { model: string; effort: string | null }>()
  /** Sessions made with session/new, in order. */
  readonly created: string[] = []
  /** A session/new waits for this before it answers (a slow start). */
  newGate: Promise<void> | null = null

  constructor(private readonly sessionId: string, private readonly lockedSessions: Set<string> = new Set(), readonly args: string[] = ["acp", "--agent", "sdpm-orchestrator"]) { super() }

  get engine(): "v2" | "v3" { return this.args.includes("--agent-engine") ? "v3" : "v2" }

  private get agent(): string { return this.args[this.args.indexOf("--agent") + 1] ?? "" }

  /** A session's model and effort (a session with none yet starts on `auto`). */
  config(sessionId: string): { model: string; effort: string | null } {
    let config = this.configs.get(sessionId)
    if (!config) this.configs.set(sessionId, (config = { model: "auto", effort: null }))
    return config
  }

  /** The model of the child's first session (or of `sessionId`). */
  model(sessionId: string = this.sessionId): string {
    return this.config(sessionId).model
  }

  /** The sdpm server's state for a session, in the engine's shape, ahead of the answer (as V2 sends it). */
  private mcpReady(sessionId: string) {
    if (this.mcpState === "none") return
    if (this.engine === "v2") {
      const failed = this.mcpState === "failed"
      this.send({ method: failed ? "_kiro.dev/mcp/server_init_failure" : "_kiro.dev/mcp/server_initialized", params: { sessionId, serverName: "sdpm", ...(failed ? { error: "connection closed" } : {}) } })
    } else {
      this.send({ method: "_kiro/mcp/status", params: { sessionId, servers: [{ name: "sdpm", status: this.mcpState, ...(this.mcpState === "failed" ? { errorMessage: "Connection closed" } : {}) }] } })
    }
  }

  private modes(current: string) {
    return { currentModeId: current, availableModes: ["sdpm-orchestrator", "sdpm-composer", "sdpm-style", "sdpm-translate"].map((id) => ({ id, name: id })) }
  }

  /** V3's config options of a session: the model list, and the effort option of a model with effort. */
  configOptions(sessionId: string = this.sessionId) {
    const { model, effort } = this.config(sessionId)
    const options: Record<string, unknown>[] = [{
      type: "select", id: "model", category: "model", currentValue: model,
      options: FAKE_MODELS.map((value) => ({ value, name: value.toUpperCase(), _meta: { kiro: value === "m-effort" ? { hasEffort: true, effortLevels: ["low", "high"], defaultEffortLevel: "low", rateMultiplier: 2 } : { hasEffort: false } } })),
    }]
    if (model === "m-effort") options.push({ type: "select", id: "effortLevel", category: "thought_level", currentValue: effort ?? "low", options: [{ value: "low" }, { value: "high" }] })
    return options
  }

  private configUpdate(sessionId: string) {
    this.update(sessionId, { sessionUpdate: "config_option_update", configOptions: this.configOptions(sessionId) })
  }

  send(msg: Record<string, unknown>) {
    // Answer after rpcRequestTo has registered the pending request.
    setImmediate(() => this.stdout.emit("data", JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n"))
  }

  /** The id the next session/new answers. */
  private nextSessionId(): string {
    return this.created.length === 0 ? this.sessionId : `${this.sessionId}-${this.created.length + 1}`
  }

  private handle(req: Rpc) {
    if (req.method === undefined) { this.answers.push(req as unknown as Record<string, unknown>); return }
    if (req.method === "session/cancel") this.cancelled.push(req.params.sessionId as string)
    if (req.id == null) return
    this.requests.push(req)
    if (this.silent.has(req.method)) return
    if (req.method === "initialize" && !this.failing.has(req.method)) {
      this.send({ id: req.id, result: {
        protocolVersion: 1,
        agentCapabilities: { loadSession: true, sessionCapabilities: this.engine === "v3" ? { list: {}, close: {}, delete: {}, fork: {} } : {} },
      } })
      return
    }
    if (req.method === "_session/steer" && !this.failing.has(req.method)) { this.send({ id: req.id, result: this.steerAnswer }); return }
    if (req.method === "session/new") {
      const sessionId = this.nextSessionId()
      this.created.push(sessionId)
      const answer = () => {
        const requested = this.engine === "v3" ? ((req.params._meta as { kiro?: { modeId?: string } } | undefined)?.kiro?.modeId ?? "") : this.agent
        this.mcpReady(sessionId)
        if (this.engine === "v3") this.configUpdate(sessionId)
        this.send({ id: req.id, result: {
          sessionId, modes: this.modes(this.newMode ?? requested),
          ...(this.engine === "v3"
            ? { configOptions: this.configOptions(sessionId) }
            : { models: { currentModelId: this.model(sessionId), availableModels: FAKE_MODELS.map((modelId) => ({ modelId, name: modelId })) } }),
        } })
      }
      if (this.newGate) void this.newGate.then(answer)
      else answer()
    } else if (req.method === "session/load" && this.lockedSessions.has(req.params.sessionId as string)) {
      this.send({ id: req.id, error: { message: "Internal error", data: "Failed to start session: Session is active in another process (PID 1)" } })
    } else if (req.method === "session/load" && this.engine === "v2" && this.missing.has(req.params.sessionId as string)) {
      this.send({ id: req.id, error: { code: -32603, message: "Internal error", data: `Failed to start session: Session not found: ${req.params.sessionId}` } })
    } else if (req.method === "session/load") {
      const sessionId = req.params.sessionId as string
      const created = this.missing.has(sessionId)
      // kiro-cli replays the loaded session's history under its id before answering.
      if (!created) this.update(sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "earlier" }, ...(this.engine === "v3" ? { _meta: { kiro: { replay: true } } } : {}) })
      this.mcpReady(sessionId)
      this.send({ id: req.id, result: {
        modes: this.modes(this.loadedMode ?? (this.engine === "v3" ? "sdpm-orchestrator" : this.agent)),
        ...(this.engine === "v3" ? { _meta: {
          createdAt: created ? new Date().toISOString() : "2026-01-01T00:00:00.000Z",
          ...(this.forks.has(sessionId) ? { parentSessionId: this.forks.get(sessionId) } : {}),
        } } : {}),
      } })
      if (this.engine === "v3") this.configUpdate(sessionId)
    } else if (req.method === "session/fork") {
      const forkId = `F${this.forks.size + 1}`
      this.forks.set(forkId, req.params.sessionId as string)
      this.send({ id: req.id, result: { sessionId: forkId } })
    } else if (req.method === "session/set_mode") {
      this.mcpReady(req.params.sessionId as string)
      this.send({ id: req.id, result: {} })
    } else if (req.method === "session/set_config_option" && this.engine === "v3" && !this.failing.has(req.method)) {
      const config = this.config(req.params.sessionId as string)
      if (req.params.configId === "model") {
        config.model = req.params.value as string
        config.effort = null
      } else if (req.params.configId === "effortLevel") config.effort = req.params.value as string
      this.configUpdate(req.params.sessionId as string)
      this.send({ id: req.id, result: { configOptions: this.configOptions(req.params.sessionId as string) } })
    } else if (req.method === "session/set_model" && this.engine === "v2" && !this.failing.has(req.method)) {
      this.config(req.params.sessionId as string).model = req.params.modelId as string
      this.send({ id: req.id, result: {} })
    } else if (req.method === "session/prompt") {
      this.prompts.push({ id: req.id, sessionId: req.params.sessionId as string })
    } else if (this.failing.has(req.method)) {
      this.send({ id: req.id, error: { message: "Internal error", data: `${req.method} failed` } })
    } else {
      if (req.method === "session/close") this.closed.push(req.params.sessionId as string)
      if (req.method === "session/delete") this.deleted.push(req.params.sessionId as string)
      this.send({ id: req.id, result: {} })
    }
  }

  update(sessionId: string, update: Record<string, unknown>) {
    this.send({ method: "session/update", params: { sessionId, update } })
  }

  /**
   * What kiro-cli 2.37 sends for a use_subagent call: sub-session updates and list_update, no
   * turn_end. `finish: false` leaves the sub-agent working.
   */
  runSubagent(subSessionId: string, finish = true) {
    this.send({ method: "_kiro.dev/subagent/list_update", params: { subagents: [{ sessionId: subSessionId, status: { type: "working" } }] } })
    this.update(subSessionId, { sessionUpdate: "tool_call", toolCallId: `${subSessionId}-t`, title: "Running: @sdpm/generate_pptx", _meta: { kiro: { toolName: "generate_pptx", mcpServerName: "sdpm" } } })
    this.update(subSessionId, { sessionUpdate: "tool_call_update", toolCallId: `${subSessionId}-t`, status: "completed" })
    if (!finish) return
    this.send({ method: "_kiro.dev/subagent/list_update", params: { subagents: [{ sessionId: subSessionId, status: { type: "terminated" } }] } })
    this.send({ method: "_kiro.dev/subagent/list_update", params: { subagents: [] } })
  }

  /** A main-session MCP tool call whose result is `result` (the V2 shape). */
  toolResult(sessionId: string, toolCallId: string, result: Record<string, unknown>) {
    this.update(sessionId, { sessionUpdate: "tool_call", toolCallId, title: "Running: @sdpm/init_presentation", rawInput: {}, _meta: { kiro: { toolName: "init_presentation", mcpServerName: "sdpm" } } })
    this.update(sessionId, {
      sessionUpdate: "tool_call_update", toolCallId, status: "completed", title: "Running: @sdpm/init_presentation",
      rawOutput: { items: [{ Json: { content: [{ type: "text", text: JSON.stringify(result) }] } }] },
    })
  }

  /** Take the oldest unanswered prompt of `sessionId` (of any session without one). */
  private takePrompt(sessionId?: string): number | undefined {
    const at = sessionId === undefined ? 0 : this.prompts.findIndex((p) => p.sessionId === sessionId)
    if (at < 0 || at >= this.prompts.length) return undefined
    return this.prompts.splice(at, 1)[0].id
  }

  endTurn(stopReason = "end_turn", sessionId?: string) {
    this.send({ id: this.takePrompt(sessionId), result: { stopReason } })
  }

  failPrompt(sessionId?: string) {
    this.send({ id: this.takePrompt(sessionId), error: { message: "Internal error", data: "model stream failed" } })
  }

  kill() {
    if (!this.killed) {
      this.killed = true
      setImmediate(() => this.emit("close", null))
    }
    return true
  }

  /** It exits on its own (a crash): `exit`, then the end of stdout. Its descendants stay. */
  exit(code: number | null = 1) {
    if (this.killed || this.exited) return
    this.exited = true
    setImmediate(() => {
      this.emit("exit", code)
      this.stdout.emit("close")
    })
  }

  /** A fake descendant in a group of its own (V3's KAS, a V2 MCP server); returns it. */
  addDescendant(pgid?: number): FakeDescendant {
    const pid = nextFakePid()
    const descendant = { pid, pgid: pgid ?? pid, ppid: this.pid }
    this.descendants.push(descendant)
    return descendant
  }
}

export const tick = () => new Promise((r) => setImmediate(r))
export const settle = async () => { for (let i = 0; i < 10; i++) await tick() }
