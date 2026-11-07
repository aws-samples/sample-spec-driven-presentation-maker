// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V3 conversation: kiro-cli started with `--agent-engine v3` runs the sdpm agents as modes,
 * chosen per session with `_meta.kiro.modeId` on session/new. The session runs the agent's
 * mode when the answer's `modes.currentModeId` is the agent (V3 falls back to `vibe` for a
 * definition it rejects, and says why in `_kiro/customAgent/not_found`).
 *
 * An existing session is opened with session/load alone. V3 answers a load of an id it does not
 * have by creating an empty session under that id: the answer's `_meta.createdAt` later than the
 * load's start (less a second) means `created`. A session V3 imported from V2 keeps its V2
 * creation time, so it is `resumed`; without a readable `createdAt` the load counts as resumed.
 * V3 ignores a mode on session/load, so a loaded session in another mode is switched with
 * session/set_mode (its MCP record cleared first). Either way the session is returned once its
 * sdpm server is ready; V3 answers session/new and session/set_mode before it is.
 *
 * A fork is session/fork (V3's own sessions and V2 sessions alike: V3 imports a V2 one) into
 * this session's cwd and the agent's mode, then a load of the new id as above. The load of a fork
 * names its source in `_meta.parentSessionId`: another source means kiro-cli did not fork it
 * (`created`); none is taken as resumed. `createdAt` is the fork's time and says nothing here.
 * `discardFork` deletes (session/delete) only a fork this session made.
 */
import { AgentStartError } from "../../../turnErrors"
import type { AcpModelList, EngineErrorKind, EngineSession, ForkSessionOptions, LoadOutcome, OpenSessionOptions, SessionContext } from "../../engine"
import type { AcpNotification, ForkSessionResponse, SessionModeState } from "../../schema"
import { AcpRequestError } from "../../transport"
import { V3Translator } from "./translate"
import type { V3LoadSessionResponse, V3NewSessionResponse } from "./types"

/** ACP's "authentication required" error code. */
const AUTH_REQUIRED = -32000
/** How long a failed mode check waits for kiro-cli's `customAgent/not_found` (sent shortly after the answer). */
const NOT_FOUND_GRACE_MS = 2000
/** A session created this long before the load started still counts as created by it (clock granularity). */
const CREATED_MARGIN_MS = 1000

export class V3Session implements EngineSession {
  private readonly translator = new V3Translator()
  private notFound: Promise<void>
  private notFoundSeen = () => {}
  /** Forks this session made (`forkSession`): the only ids `discardFork` deletes. */
  private readonly forks = new Set<string>()

  constructor(private readonly ctx: SessionContext) {
    this.notFound = new Promise((resolve) => { this.notFoundSeen = resolve })
    this.translator.onAgentNotFound = () => this.notFoundSeen()
  }

  async newSession(agentName: string): Promise<{ sessionId: string }> {
    const result = await this.ctx.request("session/new", {
      cwd: this.ctx.cwd, mcpServers: [], _meta: { kiro: { modeId: agentName } },
    }, { timeoutMs: this.ctx.setupTimeoutMs, signal: this.ctx.signal }) as V3NewSessionResponse
    this.translator.mainSessionId = result.sessionId
    if (result.modes?.currentModeId !== agentName) await this.rejected(agentName, result.modes?.currentModeId)
    await this.ctx.waitForMcp(result.sessionId)
    return { sessionId: result.sessionId }
  }

  async openSession(sessionId: string, agentName: string, opts: OpenSessionOptions = {}): Promise<{ sessionId: string; outcome: LoadOutcome }> {
    const startedAt = Date.now()
    const loaded = await this.load(sessionId, agentName, opts)
    return { sessionId, outcome: loadOutcome(sessionId, loaded?._meta?.createdAt, startedAt) }
  }

  async forkSession(sourceId: string, agentName: string, opts: ForkSessionOptions = {}): Promise<{ sessionId: string; outcome: LoadOutcome }> {
    opts.onCopying?.()
    const forked = await this.ctx.request("session/fork", {
      sessionId: sourceId, cwd: this.ctx.cwd, mcpServers: [], _meta: { kiro: { modeId: agentName } },
    }, { timeoutMs: this.ctx.setupTimeoutMs, signal: this.ctx.signal }) as ForkSessionResponse
    const forkId = forked?.sessionId
    if (typeof forkId !== "string" || !forkId) throw new Error(`session/fork of ${sourceId} answered no sessionId`)
    this.forks.add(forkId)
    opts.onForked?.(forkId)
    const loaded = await this.load(forkId, agentName, opts)
    return { sessionId: forkId, outcome: forkOutcome(forkId, sourceId, loaded?._meta?.parentSessionId) }
  }

  async discardFork(sessionId: string): Promise<void> {
    if (!this.forks.delete(sessionId)) {
      console.warn("[acp] V3: not deleting session %s, which this session did not fork", sessionId)
      return
    }
    await this.ctx.request("session/delete", { sessionId }, { timeoutMs: this.ctx.setupTimeoutMs })
  }

  translate(msg: AcpNotification): ReturnType<EngineSession["translate"]> {
    return this.translator.translate(msg)
  }

  beginTurn(): void {}

  endTurn(): void {}

  /** V3 runs sub-agents inside the main session: cancelling it stops them. */
  cancelTargets(): string[] {
    return this.translator.mainSessionId ? [this.translator.mainSessionId] : []
  }

  models(): AcpModelList | null {
    return this.translator.models()
  }

  classifyError(error: unknown): EngineErrorKind | null {
    if (error instanceof AcpRequestError && error.code === AUTH_REQUIRED) return "auth_required"
    return null
  }

  /** session/load (the replay reported), then the agent's mode and the sdpm server. */
  private async load(sessionId: string, agentName: string, opts: OpenSessionOptions): Promise<V3LoadSessionResponse> {
    this.translator.startLoad(sessionId, opts.onReplay)
    const loaded = await this.ctx.request("session/load", { sessionId, cwd: this.ctx.cwd, mcpServers: [] }, {
      timeoutMs: this.ctx.setupTimeoutMs,
      signal: this.ctx.signal,
      onAnswer: () => this.translator.finishLoad(),
    }) as V3LoadSessionResponse
    if (loaded?.modes?.currentModeId !== agentName) await this.switchMode(sessionId, agentName, loaded?.modes, opts)
    await this.ctx.waitForMcp(sessionId)
    return loaded
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

function loadOutcome(sessionId: string, createdAt: unknown, startedAt: number): LoadOutcome {
  const created = typeof createdAt === "string" ? Date.parse(createdAt) : NaN
  if (Number.isNaN(created)) {
    console.warn("[acp] session/load of %s answered no readable _meta.createdAt (%j); treating it as resumed", sessionId, createdAt)
    return "resumed"
  }
  if (created < startedAt - CREATED_MARGIN_MS) return "resumed"
  console.info("[acp] V3 had no session %s; it starts empty", sessionId)
  return "created"
}

function forkOutcome(forkId: string, sourceId: string, parentSessionId: unknown): LoadOutcome {
  if (parentSessionId === sourceId) return "resumed"
  if (typeof parentSessionId !== "string") {
    console.warn("[acp] session/load of the fork %s answered no _meta.parentSessionId; treating it as forked from %s", forkId, sourceId)
    return "resumed"
  }
  console.warn("[acp] session/load of the fork %s names %s as its source, not %s", forkId, parentSessionId, sourceId)
  return "created"
}
