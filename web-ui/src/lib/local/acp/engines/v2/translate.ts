// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V2's notifications as LocalEvents. One translator per kiro session (a kiro-cli may carry
 * several, each line reaches every one of them).
 *
 * Each `session/update` / `_kiro.dev/session/update` is read by the first rule that applies:
 * 1. An update of the session being loaded, before the load's answer: the replay → [] (counted
 *    for the load's progress).
 * 2. An update of another session than the main one: a sub-agent's session. A session the
 *    running crew (the delegation to the composer) maps to one of its groups sends that group's
 *    `composer_tool` / `composer_tool_end` (its tool_call / finished tool_call_update). Anything
 *    else a sub-agent sends (its text, thoughts, tool chunks), and anything from a session no
 *    group is mapped to → [], so none of it reaches the main chat.
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
 *      when no call announced the tool); the crew's own update first ends every group still
 *      running with `composer_end` of the same status.
 * `_kiro.dev/subagent/list_update` (the full list of sub-agents): a session named after a stage
 * of the running crew (`sessionName`) is mapped to that stage's group; a mapped session whose
 * status is `terminated` ends its group (`composer_end success`), any other status but `working`
 * ends it failed. The sessions listed `working` are the ones Stop cancels besides the main one.
 * `AgentExecutionSteeringInjected` of the main session → `steer_injected`.
 * MCP state is read once per line for the whole kiro-cli (`v2McpEvents`, the adapter's
 * `translateMcp`, any session, also one whose session/new is not answered yet):
 * `_kiro.dev/mcp/server_initialized` → `mcp_status connected`, `server_init_failure` →
 * `mcp_status failed`; the translator returns [] for them. `_kiro.dev/agent/not_found` is logged and reported to
 * `onAgentNotFound` (the session's mode check waits for it to say why).
 */
import type { LocalEvent } from "../../../conversation/events"
import type { AcpNotification } from "../../schema"
import {
  KIRO_AGENT_NOT_FOUND, KIRO_MCP_SERVER_INIT_FAILURE, KIRO_MCP_SERVER_INITIALIZED, KIRO_SESSION_UPDATE, KIRO_SUBAGENT_LIST_UPDATE,
  type V2CrewInput, type V2SubagentListUpdate, type V2ToolMeta, type V2ToolOutput,
} from "./types"

/** The crew's tool name in `_meta.kiro.toolName` and its chunk's title. */
const CREW_TOOL = "subagent"
const COMPOSE_TOOL = "compose_slides"

type Update = Record<string, unknown> & { sessionUpdate?: string }

interface Crew {
  toolCallId: string
  /** The stages in order: their group key (the stage name, made unique) and their name. */
  stages: { group: string; name: string }[]
  /** Sub-agent session → its group. */
  children: Map<string, string>
  /** The groups that ended. */
  ended: Set<string>
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

/** A line's MCP state, whichever session it names: `server_initialized` → connected, `server_init_failure` → failed. */
export function v2McpEvents(msg: AcpNotification): LocalEvent[] {
  if (msg.method !== KIRO_MCP_SERVER_INITIALIZED && msg.method !== KIRO_MCP_SERVER_INIT_FAILURE) return []
  const params = objectOr(msg.params)
  if (typeof params.sessionId !== "string" || typeof params.serverName !== "string") return []
  if (msg.method === KIRO_MCP_SERVER_INITIALIZED) return [{ type: "mcp_status", sessionId: params.sessionId, server: params.serverName, state: "connected" }]
  const error = typeof params.error === "string" ? { error: params.error } : {}
  return [{ type: "mcp_status", sessionId: params.sessionId, server: params.serverName, state: "failed", ...error }]
}

export class V2Translator {
  /** The session prompts go to. */
  mainSessionId: string | null = null
  private loading: { sessionId: string; replayed: number; onReplay?: (replayed: number, done: boolean) => void } | null = null
  /** The sub-agent sessions the last list_update has `working`. */
  private working: string[] = []
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

  /** A turn starts or ends: a crew of an earlier turn maps no session any more. */
  beginTurn(): void {
    this.crew = null
  }

  endTurn(): void {
    this.crew = null
  }

  /** The sub-agent sessions kiro-cli last listed as working. */
  workingChildren(): string[] {
    return [...this.working]
  }

  translate(msg: AcpNotification): LocalEvent[] {
    if (msg.method === KIRO_MCP_SERVER_INITIALIZED || msg.method === KIRO_MCP_SERVER_INIT_FAILURE) return []
    if (msg.method === KIRO_SUBAGENT_LIST_UPDATE) return this.listUpdate(objectOr(msg.params) as V2SubagentListUpdate)
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
    const group = this.crew?.children.get(sessionId)
    if (group === undefined) return []
    const id = typeof update.toolCallId === "string" ? update.toolCallId : ""
    if (update.sessionUpdate === "tool_call") {
      return [{ type: "composer_tool", group, id, name: toolName(update), input: objectOr(update.rawInput) }]
    }
    if (update.sessionUpdate === "tool_call_update" && (update.status === "completed" || update.status === "failed")) {
      return [{ type: "composer_tool_end", group, id, status: update.status === "completed" ? "success" : "error" }]
    }
    return []
  }

  private listUpdate(params: V2SubagentListUpdate): LocalEvent[] {
    const subagents = (Array.isArray(params.subagents) ? params.subagents : [])
      .filter((agent): agent is typeof agent & { sessionId: string } => isObject(agent) && typeof agent.sessionId === "string")
    this.working = subagents.filter((agent) => agent.status?.type === "working").map((agent) => agent.sessionId)
    const crew = this.crew
    if (!crew) return []
    const events: LocalEvent[] = []
    for (const agent of subagents) {
      let group = crew.children.get(agent.sessionId)
      if (group === undefined) {
        const mapped = new Set(crew.children.values())
        group = crew.stages.find((stage) => stage.name === agent.sessionName && !mapped.has(stage.group))?.group
        if (group === undefined) continue
        crew.children.set(agent.sessionId, group)
      }
      const state = agent.status?.type
      if (!state || state === "working" || crew.ended.has(group)) continue
      crew.ended.add(group)
      events.push({ type: "composer_end", group, status: state === "terminated" ? "success" : "error" })
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
        const status = update.status === "completed" ? "success" : "error"
        const events: LocalEvent[] = this.crew?.toolCallId === id ? this.crewEnded(status) : []
        const name = typeof update.title === "string" && update.title ? { name: update.title } : {}
        events.push({ type: "tool_end", id, status, result: toolResult(update.rawOutput), ...name })
        return events
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
    const stages: Crew["stages"] = []
    const events: LocalEvent[] = (Array.isArray(input?.stages) ? input.stages : []).map((stage, i) => {
      const name = typeof stage?.name === "string" ? stage.name : ""
      const group = name && !stages.some((s) => s.group === name) ? name : `#${i + 1}`
      stages.push({ group, name })
      return { type: "composer_start", group, prompt: stage?.prompt_template || name, toolCallId }
    })
    this.crew = { toolCallId, stages, children: new Map(), ended: new Set() }
    return events
  }

  /** The crew's tool call ended: every group still running ends with it, and the crew maps no session any more. */
  private crewEnded(status: "success" | "error"): LocalEvent[] {
    const crew = this.crew!
    this.crew = null
    return crew.stages.filter((stage) => !crew.ended.has(stage.group)).map((stage) => ({ type: "composer_end", group: stage.group, status }))
  }
}
