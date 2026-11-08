// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V3's notifications as LocalEvents. One translator per kiro session (a kiro-cli may carry
 * several, each line reaches every one of them).
 *
 * V3 has no sub-agent sessions: a sub-agent's updates arrive in the main session with
 * `_meta.kiro.agentSubtaskId`. Updates of another session are dropped.
 *
 * Text and thoughts (`agent_message_chunk` / `agent_thought_chunk`), first rule that applies:
 * 1. replayed (`_meta.kiro.replay`) → [] (counted for the load's progress),
 * 2. from a sub-agent (`agentSubtaskId`) → [],
 * 3. the main session's text → `text`; its thoughts → [].
 *
 * Tool updates (`tool_call` / `tool_call_update`), first rule that applies:
 * 1. replayed → [].
 * 2. a delegation (`kind: "agent-subtask"`, which also carries its own agentSubtaskId):
 *    to `sdpm-composer` → `composer_start {group: agentSubtaskId}` on its call and `composer_end`
 *    when it completed or failed; to any other agent → one plain tool card (`tool_use` named by
 *    the agent, `tool_end`), whose inner tools are not shown.
 * 3. kiro-cli's internal calls → []: tool loading ("Tool Load": no serverName, `rawInput.tool_ids`)
 *    and a sub-agent's answer to its parent (`toolOrigin: "acp"`), call or update, from the main
 *    session or a sub-agent.
 * 4. inside a sub-agent (`agentSubtaskId`): a composer's tools → `composer_tool` on the call,
 *    `composer_tool_end` when completed or failed; any other sub-agent's → [].
 * 5. the main session's tools → `tool_use` on the call (an MCP tool named by `rawInput.tool_id`
 *    without its `<server>::`, else by its title without `@<server>/`; a built-in one by its
 *    title; an MCP tool's input is `rawInput.arguments`, a built-in one's `rawInput`) and
 *    `tool_end` when completed or failed (the result is `rawOutput.response` or the `content[]`
 *    text, parsed as JSON; a failure's is `{message: rawOutput.message}`). An update that ends a
 *    tool no call announced gets its `tool_use` first, from the update itself.
 *
 * MCP state is read once per line for the whole kiro-cli (`v3McpEvents`, the adapter's
 * `translateMcp`): `_kiro/mcp/status` (a full snapshot) → `mcp_snapshot` then one `mcp_status` per
 * server; the translator returns [] for it.
 *
 * Other notifications: `session_info_update` with `kind: "steering_injected"` →
 * `steer_injected`; `config_option_update` keeps the session's model, effort and model list
(kiro-cli sends one before it answers set_config_option and after a load's answer, whose own
`configOptions` list only the current values; a new session's first one comes before session/new
is answered, so the session reads that answer's full list with `readConfig`); a custom agent that was
 * not found or not readable is logged (`onAgentNotFound` is told the former).
 */
import type { LocalEvent, ToolEndStatus } from "../../../conversation/events"
import type { ModelOption, SessionModels } from "../../engine"
import type { AcpNotification } from "../../schema"
import {
  KIRO_CUSTOM_AGENT_CONFIG_ERROR, KIRO_CUSTOM_AGENT_NOT_FOUND, KIRO_MCP_STATUS,
  type V3McpStatusParams, type V3SelectOption, type V3SubtaskInput, type V3ToolInput, type V3ToolOutput, type V3UpdateMeta,
} from "./types"

const COMPOSER_AGENT = "sdpm-composer"

type Update = Record<string, unknown> & { sessionUpdate?: string }

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)

const objectOr = (value: unknown): Record<string, unknown> => (isObject(value) ? value : {})

function kiroMeta(update: Record<string, unknown>): V3UpdateMeta {
  const meta = update._meta
  return isObject(meta) && isObject(meta.kiro) ? (meta.kiro as V3UpdateMeta) : {}
}

function parseObject(text: unknown): Record<string, unknown> {
  if (typeof text !== "string" || !text) return {}
  try { return objectOr(JSON.parse(text)) } catch { return {} }
}

/** An MCP tool's own name; a built-in tool's title. */
function toolName(update: Update, meta: V3UpdateMeta): string {
  const title = typeof update.title === "string" ? update.title : ""
  const server = meta.serverName
  if (!server) return title
  const toolId = (update.rawInput as V3ToolInput | undefined)?.tool_id
  if (typeof toolId === "string" && toolId.startsWith(`${server}::`)) return toolId.slice(server.length + 2)
  return title.startsWith(`@${server}/`) ? title.slice(server.length + 2) : title
}

/** An MCP tool's input is wrapped (`{tool_id, arguments}`); a built-in tool's is `rawInput` itself. */
function toolInput(update: Update, meta: V3UpdateMeta): Record<string, unknown> {
  if (!meta.serverName) return objectOr(update.rawInput)
  return objectOr((update.rawInput as V3ToolInput | undefined)?.arguments)
}

/** A finished tool's result: its `rawOutput.response`, else its `content[]` text; a failure's message. */
function toolResult(update: Update, status: ToolEndStatus): Record<string, unknown> {
  const output = objectOr(update.rawOutput) as V3ToolOutput
  if (status === "error") return typeof output.message === "string" ? { message: output.message } : {}
  if (typeof output.response === "string") return parseObject(output.response)
  const content = Array.isArray(update.content) ? update.content : []
  const text = content
    .map((block) => objectOr(objectOr(block).content).text)
    .filter((t): t is string => typeof t === "string")
    .join("")
  return parseObject(text)
}

function finished(update: Update): ToolEndStatus | null {
  if (update.status === "completed") return "success"
  if (update.status === "failed") return "error"
  return null
}

/** kiro-cli's own calls that are not tools: tool loading and a sub-agent's answer. */
function isInternal(update: Update, meta: V3UpdateMeta): boolean {
  if (meta.toolOrigin === "acp") return true
  return !meta.serverName && Array.isArray((update.rawInput as V3ToolInput | undefined)?.tool_ids)
}

/** A line's MCP state, whichever session it names: `_kiro/mcp/status` → `mcp_snapshot` and one `mcp_status` per server. */
export function v3McpEvents(msg: AcpNotification): LocalEvent[] {
  if (msg.method !== KIRO_MCP_STATUS) return []
  const params = objectOr(msg.params) as V3McpStatusParams
  if (typeof params.sessionId !== "string") return []
  const sessionId = params.sessionId
  const events: LocalEvent[] = [{ type: "mcp_snapshot", sessionId }]
  for (const server of Array.isArray(params.servers) ? params.servers : []) {
    if (typeof server?.name !== "string") continue
    const state = server.status === "connected" ? "connected" : server.status === "failed" ? "failed" : "connecting"
    const error = typeof server.errorMessage === "string" ? { error: server.errorMessage } : {}
    events.push({ type: "mcp_status", sessionId, server: server.name, state, ...error })
  }
  return events
}

export class V3Translator {
  /** The session prompts go to. */
  mainSessionId: string | null = null
  /** Called with `_kiro/customAgent/not_found`'s params. */
  onAgentNotFound: ((params: Record<string, unknown>) => void) | null = null
  private replayed = 0
  private onReplay: ((replayed: number, done: boolean) => void) | null = null
  /** agentSubtaskId → whether the delegation went to the composer. */
  private readonly subtasks = new Map<string, "composer" | "other">()
  /** Main-session tool calls already announced with `tool_use`. */
  private readonly announced = new Set<string>()
  private modelList: SessionModels | null = null
  /** The ids of the model and effort options in the last `config_option_update`. */
  private optionIds: { model: string; effort: string | null } = { model: "model", effort: null }

  /** A session/load of `sessionId` starts: replayed updates are counted until `finishLoad`. */
  startLoad(sessionId: string, onReplay?: (replayed: number, done: boolean) => void): void {
    this.mainSessionId = sessionId
    this.replayed = 0
    this.onReplay = onReplay ?? null
    onReplay?.(0, false)
  }

  finishLoad(): void {
    this.onReplay?.(this.replayed, true)
    this.onReplay = null
  }

  /** The model, effort and models of the session's last `config_option_update`, or null before one. */
  models(): SessionModels | null {
    return this.modelList
  }

  /** The config option ids set_config_option takes for the model and the effort (null: the model has none). */
  configIds(): { model: string; effort: string | null } {
    return this.optionIds
  }

  translate(msg: AcpNotification): LocalEvent[] {
    const params = objectOr(msg.params)
    switch (msg.method) {
      case KIRO_MCP_STATUS:
        return []
      case KIRO_CUSTOM_AGENT_NOT_FOUND:
        console.warn("[acp] kiro-cli did not start the custom agent: %j", params)
        this.onAgentNotFound?.(params)
        return []
      case KIRO_CUSTOM_AGENT_CONFIG_ERROR:
        console.warn("[acp] kiro-cli could not read an agent file: %j", params)
        return []
      case "session/update":
        break
      default:
        return []
    }
    const update = params.update
    if (params.sessionId !== this.mainSessionId || !isObject(update)) return []
    const meta = kiroMeta(update)
    if (meta.replay === true) {
      this.replayed++
      this.onReplay?.(this.replayed, false)
      return []
    }
    switch (update.sessionUpdate) {
      case "agent_message_chunk": {
        if (meta.agentSubtaskId) return []
        const text = objectOr(update.content).text
        return typeof text === "string" && text ? [{ type: "text", text }] : []
      }
      case "tool_call":
      case "tool_call_update":
        return this.tool(update, meta)
      case "session_info_update":
        if (meta.kind !== "steering_injected") return []
        return [{
          type: "steer_injected",
          ...(typeof meta.messageId === "string" ? { messageId: meta.messageId } : {}),
          ...(typeof meta.content === "string" ? { content: meta.content } : {}),
        }]
      case "config_option_update":
        this.readConfig(update.configOptions)
        return []
      default:
        // agent_thought_chunk, plan, usage, user_message_chunk, ... (shown from phase 3 on, if at all)
        return []
    }
  }

  private tool(update: Update, meta: V3UpdateMeta): LocalEvent[] {
    const id = typeof update.toolCallId === "string" ? update.toolCallId : ""
    const isCall = update.sessionUpdate === "tool_call"
    const end = isCall ? null : finished(update)

    if (meta.kind === "agent-subtask" && meta.agentSubtaskId) {
      const subtask = meta.agentSubtaskId
      const input = objectOr(update.rawInput) as V3SubtaskInput
      if (isCall) {
        if (input.name === COMPOSER_AGENT) {
          this.subtasks.set(subtask, "composer")
          return [{ type: "composer_start", group: subtask, prompt: typeof input.prompt === "string" ? input.prompt : "", toolCallId: id }]
        }
        this.subtasks.set(subtask, "other")
        this.announced.add(id)
        return [{ type: "tool_use", id, name: input.name ?? "", input: objectOr(update.rawInput) }]
      }
      if (!end) return []
      const kind = this.subtasks.get(subtask) ?? (input.name === COMPOSER_AGENT ? "composer" : "other")
      if (kind === "composer") return [{ type: "composer_end", group: subtask, status: end }]
      return [{ type: "tool_end", id, status: end, result: toolResult(update, end), ...(input.name ? { name: input.name } : {}) }]
    }

    if (isInternal(update, meta)) return []

    if (meta.agentSubtaskId) {
      const group = meta.agentSubtaskId
      if (this.subtasks.get(group) !== "composer") return []
      if (isCall) return [{ type: "composer_tool", group, id, name: toolName(update, meta), input: toolInput(update, meta) }]
      return end ? [{ type: "composer_tool_end", group, id, status: end }] : []
    }

    if (isCall) {
      this.announced.add(id)
      return [{ type: "tool_use", id, name: toolName(update, meta), input: toolInput(update, meta) }]
    }
    if (!end) return []
    const events: LocalEvent[] = []
    if (!this.announced.has(id)) {
      this.announced.add(id)
      events.push({ type: "tool_use", id, name: toolName(update, meta), input: toolInput(update, meta) })
    }
    events.push({ type: "tool_end", id, status: end, result: toolResult(update, end) })
    return events
  }

  /** Keep the model, effort and models of a list of config options (session/new's answer, a config_option_update). */
  readConfig(options: unknown): void {
    if (!Array.isArray(options)) return
    const selects = options.filter((option): option is V3SelectOption => isObject(option))
    const model = selects.find((option) => option.category === "model") ?? selects.find((option) => option.id === "model")
    if (!model || !Array.isArray(model.options)) return
    const effort = selects.find((option) => option.category === "thought_level")
    const levels = Array.isArray(effort?.options)
      ? effort.options.map((option) => option?.value).filter((value): value is string => typeof value === "string")
      : []
    this.optionIds = { model: typeof model.id === "string" ? model.id : "model", effort: effort && typeof effort.id === "string" ? effort.id : null }
    this.modelList = {
      current: typeof model.currentValue === "string" ? model.currentValue : "",
      available: model.options.filter((option) => typeof option?.value === "string" && listed(option.description)).map(modelOption),
      effort: effort && this.optionIds.effort && levels.length
        ? { current: typeof effort.currentValue === "string" ? effort.currentValue : "", levels }
        : null,
    }
  }
}

/** kiro-cli marks the models it does not offer to users in their description. */
const listed = (description: unknown) =>
  typeof description !== "string" || !(description.startsWith("[Internal]") || description.startsWith("[Deprecated]"))

const isStringList = (value: unknown): value is string[] =>
  Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string")

function modelOption(option: NonNullable<V3SelectOption["options"]>[number]): ModelOption {
  const meta = option._meta?.kiro ?? {}
  const effort = meta.hasEffort === true && isStringList(meta.effortLevels)
  return {
    modelId: option.value!,
    name: option.name || option.value!,
    ...(option.description ? { description: option.description } : {}),
    ...(effort ? { effortLevels: [...meta.effortLevels!] } : {}),
    ...(effort && typeof meta.defaultEffortLevel === "string" ? { defaultEffort: meta.defaultEffortLevel } : {}),
    ...(typeof meta.rateMultiplier === "number" && Number.isFinite(meta.rateMultiplier) ? { rate: meta.rateMultiplier } : {}),
  }
}
