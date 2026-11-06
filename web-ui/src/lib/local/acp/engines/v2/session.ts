// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A V2 conversation: kiro-cli started with `--agent <name>` runs that agent, so session/new
 * needs no agent field. An existing session is opened as session/new, then session/load of the
 * saved id (the prompts then go to the loaded id). A fork also switches the loaded session to
 * the agent's mode and waits for its sdpm server, which set_mode does not wait for.
 */
import type { AcpModelList, EngineSession, LoadOutcome, OpenSessionOptions, SessionContext } from "../../engine"
import type { AcpNotification, LoadSessionResponse } from "../../schema"
import { V2Translator } from "./translate"
import type { V2NewSessionResponse } from "./types"

export class V2Session implements EngineSession {
  private readonly translator = new V2Translator()
  private modelList: AcpModelList | null = null

  constructor(private readonly ctx: SessionContext) {}

  async newSession(): Promise<{ sessionId: string }> {
    const result = await this.ctx.request("session/new", { cwd: this.ctx.cwd, mcpServers: [] }, {
      timeoutMs: this.ctx.setupTimeoutMs, signal: this.ctx.signal,
    }) as V2NewSessionResponse
    this.translator.mainSessionId = result.sessionId
    if (result.models) {
      this.modelList = { current: result.models.currentModelId || "", available: result.models.availableModels || [] }
    }
    return { sessionId: result.sessionId }
  }

  async openSession(sessionId: string, agentName: string, opts: OpenSessionOptions = {}): Promise<{ sessionId: string; outcome: LoadOutcome }> {
    await this.newSession()
    this.translator.startLoad(sessionId, opts.onReplay)
    // Watch from before session/load: the source agent may already carry the sdpm server, and
    // after set_mode its readiness can arrive before the reply.
    const sdpmReady = opts.setMode ? this.ctx.watchMcp(sessionId) : null
    let loaded: LoadSessionResponse
    try {
      loaded = await this.ctx.request("session/load", { sessionId, cwd: this.ctx.cwd, mcpServers: [] }, {
        timeoutMs: this.ctx.setupTimeoutMs,
        signal: this.ctx.signal,
        onAnswer: (answer) => this.translator.finishLoad(answer.ok),
      }) as LoadSessionResponse
    } catch (error) {
      this.translator.finishLoad(false)
      sdpmReady?.dispose()
      throw error
    }
    if (sdpmReady) {
      if (!loaded?.modes?.availableModes?.some((mode) => mode.id === agentName)) {
        sdpmReady.dispose()
        throw new Error(`mode ${agentName} unavailable`)
      }
      opts.onSwitching?.()
      try {
        await this.ctx.request("session/set_mode", { sessionId, modeId: agentName }, { timeoutMs: this.ctx.setupTimeoutMs, signal: this.ctx.signal })
      } catch (error) {
        sdpmReady.dispose()
        throw error
      }
      // set_mode replies before the new agent's MCP servers are up; the first prompt (the
      // continuation greeting) needs start_presentation.
      if (!(await sdpmReady.wait(this.ctx.mcpReadyTimeoutMs, this.ctx.signal))) {
        console.warn("[acp] sdpm MCP server not initialized after %dms (session %s)", this.ctx.mcpReadyTimeoutMs, sessionId)
      }
    }
    return { sessionId, outcome: "resumed" }
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

  /** The main session and the sub-agent sessions this turn ran (V2 cancels each of them). */
  cancelTargets(): string[] {
    const main = this.translator.mainSessionId
    return main ? [main, ...this.translator.takeChildren()] : []
  }

  models(): AcpModelList | null {
    return this.modelList
  }
}
