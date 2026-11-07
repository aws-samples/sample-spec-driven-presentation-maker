// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V2's notifications as LocalEvents. One translator per kiro-cli process (one conversation).
 *
 * Each `session/update` / `_kiro.dev/session/update` is read by the first rule that applies:
 * 1. An update of the session being loaded, before the load's answer: the replay → [] (counted
 *    for the load's progress).
 * 2. An update of another session than the main one: a sub-agent's session. While the crew (the
 *    delegation to the composer) runs, each new sub-agent session becomes the crew's next group
 *    in arrival order; its tool_call / finished tool_call_update are the group's
 *    `composer_tool` / `composer_tool_end`. Anything else a sub-agent sends (its text, thoughts,
 *    tool chunks) → [], so none of it reaches the main chat.
 * 3. The main session's text → `text`; its thoughts and other kinds → [].
 * 4. The main session's tools:
 *    - `tool_call_chunk` → `tool_start` (its title is the tool's name; the crew's, `subagent`, is
 *      shown as compose_slides from the start),
 *    - the crew's `tool_call` (`_meta.kiro.toolName` "subagent") → one `composer_start` per
 *      `rawInput.stages[]`,
 *    - any other `tool_call` → `tool_use`, named by `_meta.kiro.toolName` for an MCP tool
 *      (`mcpServerName` set) and by its title for a built-in one; the input is `rawInput`,
 *    - a completed or failed `tool_call_update` → `tool_end` (`success` / `error`), its result
 *      read from `rawOutput.items[0].Json.content[0].text`, its `name` the update's title (shown
 *      when no call announced the tool).
 * `AgentExecutionSteeringInjected` of the main session → `steer_injected`.
 * `_kiro.dev/mcp/server_initialized` → `mcp_status connected`, `server_init_failure` →
 * `mcp_status failed` (any session). `_kiro.dev/agent/not_found` is logged and reported to
 * `onAgentNotFound` (the session's mode check waits for it to say why).
 */
import type { LocalEvent } from "../../../conversation/events"
import type { AcpNotification } from "../../schema"
import {
  KIRO_AGENT_NOT_FOUND, KIRO_MCP_SERVER_INIT_FAILURE, KIRO_MCP_SERVER_INITIALIZED, KIRO_SESSION_UPDATE,
  type V2CrewInput, type V2ToolMeta, type V2ToolOutput,
} from "./types"

/** The crew's tool name in `_meta.kiro.toolName` and its chunk's title. */
const CREW_TOOL = "subagent"
const COMPOSE_TOOL = "compose_slides"

type Update = Record<string, unknown> & { sessionUpdate?: string }

interface Crew {
  toolCallId: string
  /** Group keys, in stage order; a sub-agent session takes the next free one. */
  groups: string[]
  children: Map<string, string>
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)

const objectOr = (value: unknown): Record<string, unknown> => (isObject(value) ? value : {})

function toolMeta(update: Update): V2ToolMeta | undefined {
  const meta = update._meta
  return isObject(meta) && isObject(meta.kiro) ? (meta.kiro as V2ToolMeta) : undefined
}

/** An MCP tool's own name; a built-in tool's title. */
function toolName(update: Update): string {
  const kiro = toolMeta(update)
  if (kiro?.mcpServerName && kiro.toolName) return kiro.toolName
  return typeof update.title === "string" ? update.title : ""
}

function toolResult(rawOutput: unknown): Record<string, unknown> {
  const text = (rawOutput as V2ToolOutput | undefined)?.items?.[0]?.Json?.content?.[0]?.text
  if (!text) return {}
  try { return objectOr(JSON.parse(text)) } catch { return {} }
}

export class V2Translator {
  /** The session prompts go to. */
  mainSessionId: string | null = null
  private loading: { sessionId: string; replayed: number; onReplay?: (replayed: number, done: boolean) => void } | null = null
  private turnActive = false
  /** Sub-agent sessions seen in this turn that no cancel has reached yet. */
  private readonly turnChildren = new Set<string>()
  private crew: Crew | null = null
  /** Called with `_kiro.dev/agent/not_found`'s params. */
  onAgentNotFound: ((params: Record<string, unknown>) => void) | null = null

  /** A session/load of `sessionId` starts: its updates are the replay until `finishLoad`. */
  startLoad(sessionId: string, onReplay?: (replayed: number, done: boolean) => void): void {
    this.loading = { sessionId, replayed: 0, onReplay }
    onReplay?.(0, false)
  }

  /** The load was answered; a loaded session becomes the main one. */
  finishLoad(loaded: boolean): void {
    const loading = this.loading
    this.loading = null
    if (!loaded || !loading) return
    this.mainSessionId = loading.sessionId
    loading.onReplay?.(loading.replayed, true)
  }

  beginTurn(): void {
    this.turnActive = true
    this.turnChildren.clear()
    this.crew = null
  }

  endTurn(): void {
    this.turnActive = false
    this.turnChildren.clear()
  }

  /** The sub-agent sessions to cancel now; a session returned here is returned again only after its next update. */
  takeChildren(): string[] {
    const children = [...this.turnChildren]
    this.turnChildren.clear()
    return children
  }

  translate(msg: AcpNotification): LocalEvent[] {
    if (msg.method === KIRO_MCP_SERVER_INITIALIZED || msg.method === KIRO_MCP_SERVER_INIT_FAILURE) {
      const params = objectOr(msg.params)
      if (typeof params.sessionId !== "string" || typeof params.serverName !== "string") return []
      if (msg.method === KIRO_MCP_SERVER_INITIALIZED) return [{ type: "mcp_status", sessionId: params.sessionId, server: params.serverName, state: "connected" }]
      const error = typeof params.error === "string" ? { error: params.error } : {}
      return [{ type: "mcp_status", sessionId: params.sessionId, server: params.serverName, state: "failed", ...error }]
    }
    if (msg.method === KIRO_AGENT_NOT_FOUND) {
      const params = objectOr(msg.params)
      console.warn("[acp] kiro-cli did not find the agent: %j", params)
      this.onAgentNotFound?.(params)
      return []
    }
    if (msg.method !== "session/update" && msg.method !== KIRO_SESSION_UPDATE) return []
    const params = objectOr(msg.params)
    const sessionId = params.sessionId
    const update = params.update
    if (typeof sessionId !== "string" || !isObject(update)) return []

    if (this.loading && sessionId === this.loading.sessionId) {
      this.loading.onReplay?.(++this.loading.replayed, false)
      return []
    }
    if (sessionId !== this.mainSessionId) return this.subAgent(sessionId, update)
    return this.main(msg.method, update)
  }

  private subAgent(sessionId: string, update: Update): LocalEvent[] {
    if (this.turnActive) this.turnChildren.add(sessionId)
    const crew = this.crew
    if (!crew) return []
    const events: LocalEvent[] = []
    let group = crew.children.get(sessionId)
    if (group === undefined) {
      const index = crew.children.size
      group = crew.groups[index]
      if (group === undefined) {
        // More sub-agent sessions than stages: one more group.
        group = `#${index + 1}`
        crew.groups.push(group)
        events.push({ type: "composer_start", group, prompt: "", toolCallId: crew.toolCallId })
      }
      crew.children.set(sessionId, group)
    }
    const id = typeof update.toolCallId === "string" ? update.toolCallId : ""
    if (update.sessionUpdate === "tool_call") {
      events.push({ type: "composer_tool", group, id, name: toolName(update), input: objectOr(update.rawInput) })
    } else if (update.sessionUpdate === "tool_call_update" && (update.status === "completed" || update.status === "failed")) {
      events.push({ type: "composer_tool_end", group, id, status: update.status === "completed" ? "success" : "error" })
    }
    return events
  }

  private main(method: string, update: Update): LocalEvent[] {
    const id = typeof update.toolCallId === "string" ? update.toolCallId : ""
    switch (update.sessionUpdate) {
      case "agent_message_chunk": {
        const text = objectOr(update.content).text
        return typeof text === "string" && text ? [{ type: "text", text }] : []
      }
      case "tool_call_chunk": {
        const title = typeof update.title === "string" ? update.title : ""
        return [{ type: "tool_start", id, name: title === CREW_TOOL ? COMPOSE_TOOL : title }]
      }
      case "tool_call": {
        if (toolMeta(update)?.toolName === CREW_TOOL) return this.crewStarted(id, update.rawInput as V2CrewInput | undefined)
        return [{ type: "tool_use", id, name: toolName(update), input: objectOr(update.rawInput) }]
      }
      case "tool_call_update": {
        if (update.status !== "completed" && update.status !== "failed") return []
        if (this.crew?.toolCallId === id) this.crew = null
        const name = typeof update.title === "string" && update.title ? { name: update.title } : {}
        const status = update.status === "completed" ? "success" : "error"
        return [{ type: "tool_end", id, status, result: toolResult(update.rawOutput), ...name }]
      }
      case "AgentExecutionSteeringInjected":
        if (method !== KIRO_SESSION_UPDATE) return []
        return [{
          type: "steer_injected",
          ...(typeof update.messageId === "string" ? { messageId: update.messageId } : {}),
          ...(typeof update.content === "string" ? { content: update.content } : {}),
        }]
      default:
        return []
    }
  }

  private crewStarted(toolCallId: string, input: V2CrewInput | undefined): LocalEvent[] {
    const stages = Array.isArray(input?.stages) ? input.stages : []
    const groups: string[] = []
    const events: LocalEvent[] = stages.map((stage, i) => {
      const name = typeof stage?.name === "string" && stage.name && !groups.includes(stage.name) ? stage.name : `#${i + 1}`
      groups.push(name)
      return { type: "composer_start", group: name, prompt: stage?.prompt_template || stage?.name || "", toolCallId }
    })
    this.crew = { toolCallId, groups, children: new Map() }
    return events
  }
}
