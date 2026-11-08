// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V2 conversation: kiro-cli started with `--agent <name>` runs that agent, so session/new
 * needs no agent field. The session runs the agent's mode when session/new answers
 * `modes.currentModeId` = the agent (V2 falls back to `kiro_default` for an agent it does not
 * find, and says why in `_kiro.dev/agent/not_found`).
 *
 * An existing session is opened as session/new, then session/load of the saved id; the prompts
 * then go to the loaded id. A load answered `Session not found` keeps the new session instead
 * (outcome `created`): V2's process stays usable after a failed load. A loaded session in
 * another mode is switched with session/set_mode (its MCP record cleared first). Either way the
 * session is returned once its sdpm server is ready; V2 reports it before its answers.
 *
 * A fork is a copy of the stored session's files under a new UUID (stored-sessions.ts), opened
 * as above; `discardFork` removes only a copy this session made.
 *
 * The model is set with session/set_model; V2 has no effort. session/new and session/load
 * answer the models and the session's model, which the session keeps.
 */
import { AgentStartError } from "../../../turnErrors"
import type {
  EngineErrorKind, EngineSession, ForkSessionOptions, LoadOutcome, ModelChoice, OpenSessionOptions, SessionContext, SessionModels,
} from "../../engine"
import type { AcpNotification, SessionModeState } from "../../schema"
import { AcpRequestError } from "../../transport"
import { copyStoredSession, removeStoredSession, v2SessionsDir } from "./stored-sessions"
import { V2Translator } from "./translate"
import { SESSION_LOCKED_MARKER, SESSION_NOT_FOUND_MARKER, type V2LoadSessionResponse, type V2NewSessionResponse, type V2SessionModels } from "./types"

/** ACP's "authentication required" error code. */
const AUTH_REQUIRED = -32000
/** How long a failed mode check waits for kiro-cli's `agent/not_found` (sent right after the answer). */
const NOT_FOUND_GRACE_MS = 2000
/** kiro-cli answers session/set_model at once. */
const CONFIG_TIMEOUT_MS = 10_000

const isNotFound = (error: unknown) => error instanceof Error && error.message.includes(SESSION_NOT_FOUND_MARKER)

/** kiro-cli marks the models it does not offer to users in their description. */
const listed = (description: unknown) =>
  typeof description !== "string" || !(description.startsWith("[Internal]") || description.startsWith("[Deprecated]"))

/** The answer's models, or null when it has none. */
function readModels(models: V2SessionModels | undefined): SessionModels | null {
  if (!models || !Array.isArray(models.availableModels)) return null
  return {
    current: typeof models.currentModelId === "string" ? models.currentModelId : "",
    available: models.availableModels
      .filter((model) => typeof model?.modelId === "string" && listed(model.description))
      .map((model) => ({
        modelId: model.modelId!,
        name: model.name || model.modelId!,
        ...(model.description ? { description: model.description } : {}),
      })),
    effort: null,
  }
}

export class V2Session implements EngineSession {
  private readonly translator = new V2Translator()
  private modelList: SessionModels | null = null
  private notFound: Promise<void>
  private notFoundSeen = () => {}
  /** Copies this session made (`forkSession`): the only ids `discardFork` removes. */
  private readonly forks = new Set<string>()

  constructor(private readonly ctx: SessionContext) {
    this.notFound = new Promise((resolve) => { this.notFoundSeen = resolve })
    this.translator.onAgentNotFound = () => this.notFoundSeen()
  }

  async newSession(agentName: string): Promise<{ sessionId: string }> {
    const sessionId = await this.createSession(agentName)
    await this.ctx.waitForMcp(sessionId)
    return { sessionId }
  }

  async openSession(sessionId: string, agentName: string, opts: OpenSessionOptions = {}): Promise<{ sessionId: string; outcome: LoadOutcome }> {
    const created = await this.createSession(agentName)
    this.translator.startLoad(sessionId, opts.onReplay)
    let loaded: V2LoadSessionResponse
    try {
      loaded = await this.ctx.request("session/load", { sessionId, cwd: this.ctx.cwd, mcpServers: [] }, {
        timeoutMs: this.ctx.setupTimeoutMs,
        signal: this.ctx.signal,
        onAnswer: (answer) => this.translator.finishLoad(answer.ok),
      }) as V2LoadSessionResponse
    } catch (error) {
      this.translator.finishLoad(false)
      if (!isNotFound(error)) throw error
      console.warn("[acp] V2 has no session %s; continuing in the new session %s", sessionId, created)
      await this.ctx.waitForMcp(created)
      return { sessionId: created, outcome: "created" }
    }
    this.modelList = readModels(loaded?.models) ?? this.modelList
    if (loaded?.modes?.currentModeId !== agentName) await this.switchMode(sessionId, agentName, loaded?.modes, opts)
    await this.ctx.waitForMcp(sessionId)
    return { sessionId, outcome: "resumed" }
  }

  async forkSession(sourceId: string, agentName: string, opts: ForkSessionOptions = {}): Promise<{ sessionId: string; outcome: LoadOutcome }> {
    opts.onCopying?.()
    const forkId = await copyStoredSession(sourceId, v2SessionsDir(this.ctx.env))
    this.forks.add(forkId)
    opts.onForked?.(forkId)
    const opened = await this.openSession(forkId, agentName, opts)
    // V2 could not read the copy (it continues in a new empty session): report the copy's id, to discard.
    return opened.outcome === "created" ? { sessionId: forkId, outcome: "created" } : opened
  }

  async discardFork(sessionId: string): Promise<void> {
    if (!this.forks.delete(sessionId)) {
      console.warn("[acp] V2: not removing session %s, which this session did not fork", sessionId)
      return
    }
    await removeStoredSession(sessionId, v2SessionsDir(this.ctx.env))
  }

  translate(msg: AcpNotification): ReturnType<EngineSession["translate"]> {
    return this.translator.translate(msg)
  }

  beginTurn(): void {
    this.translator.beginTurn()
  }

  endTurn(): void {
    this.translator.endTurn()
  }

  /** The main session and the sub-agent sessions kiro-cli lists as working (V2 cancels each of them). */
  cancelTargets(): string[] {
    const main = this.translator.mainSessionId
    return main ? [main, ...this.translator.workingChildren()] : []
  }

  models(): SessionModels | null {
    return this.modelList
  }

  async setModel(choice: ModelChoice): Promise<void> {
    if (choice.effort) throw new Error("V2 has no effort")
    const sessionId = this.translator.mainSessionId
    if (!sessionId) throw new Error("no session")
    if (!choice.model) return
    await this.ctx.request("session/set_model", { sessionId, modelId: choice.model }, { timeoutMs: CONFIG_TIMEOUT_MS })
    if (this.modelList) this.modelList = { ...this.modelList, current: choice.model }
  }

  classifyError(error: unknown): EngineErrorKind | null {
    if (error instanceof AcpRequestError && error.code === AUTH_REQUIRED) return "auth_required"
    if (error instanceof Error && error.message.includes(SESSION_LOCKED_MARKER)) return "session_locked"
    return null
  }

  /** session/new, checked to run the agent's mode. */
  private async createSession(agentName: string): Promise<string> {
    const result = await this.ctx.request("session/new", { cwd: this.ctx.cwd, mcpServers: [] }, {
      timeoutMs: this.ctx.setupTimeoutMs, signal: this.ctx.signal,
    }) as V2NewSessionResponse
    this.translator.mainSessionId = result.sessionId
    this.modelList = readModels(result.models)
    const mode = result.modes?.currentModeId
    if (mode !== agentName) await this.rejected(agentName, mode)
    return result.sessionId
  }

  private async switchMode(sessionId: string, agentName: string, modes: SessionModeState | null | undefined, opts: OpenSessionOptions): Promise<void> {
    if (!modes?.availableModes?.some((mode) => mode.id === agentName)) await this.rejected(agentName, modes?.currentModeId)
    opts.onSwitching?.()
    this.ctx.clearMcp(sessionId)
    await this.ctx.request("session/set_mode", { sessionId, modeId: agentName }, { timeoutMs: this.ctx.setupTimeoutMs, signal: this.ctx.signal })
  }

  private async rejected(agentName: string, mode: string | undefined): Promise<never> {
    let timer: ReturnType<typeof setTimeout> | undefined
    await Promise.race([this.notFound, new Promise((resolve) => { timer = setTimeout(resolve, NOT_FOUND_GRACE_MS) })])
    clearTimeout(timer)
    throw new AgentStartError("agent_definition_rejected", `kiro-cli runs mode ${mode ?? "(none)"} instead of ${agentName}`)
  }
}
