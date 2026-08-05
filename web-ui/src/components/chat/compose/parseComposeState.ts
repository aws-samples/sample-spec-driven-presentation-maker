// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * parseComposeState — Pure function: streamMessages → structured state.
 *
 * The parser only exposes facts present in the stream. It does not infer
 * workflow phases such as consistency review. Activity belongs to the current
 * attempt; on retry, only the previous failure reason is retained.
 */

import { activityLabel, activityCategory, type ActivityCategory, type ActivityTranslator } from "./activityLabel"

export interface ComposeActivity {
  toolUseId: string
  tool: string
  label: string
  category: ActivityCategory
  status: "active" | "success" | "error"
}

export type AgentStatus = "starting" | "working" | "retrying" | "done" | "error"

export interface AgentState {
  groupIndex: number
  slugs: string[]
  instruction: string
  status: AgentStatus
  retryAttempt: number
  errorMsg?: string
  previousAttemptError?: string
  budgetReached?: boolean
  activity: ComposeActivity[]
}

export interface ComposeState {
  phase: "prefetching" | "running" | "building" | "done"
  statusMessage: string | null
  totalGroups: number
  doneGroupCount: number
  agents: AgentState[]
}

interface SlideGroup {
  slugs: string[]
  instruction: string
}

export function parseComposeState(
  streamMessages: Record<string, unknown>[],
  input?: Record<string, unknown>,
  t?: ActivityTranslator,
): ComposeState {
  const rawGroups = input?.slide_groups
  const slideGroups: SlideGroup[] = Array.isArray(rawGroups)
    ? rawGroups
    : typeof rawGroups === "string"
      ? (() => { try { const p = JSON.parse(rawGroups); return Array.isArray(p) ? p : [] } catch { return [] } })()
      : []

  const byGroup = new Map<number, AgentState>()

  slideGroups.forEach((g, i) => {
    byGroup.set(i + 1, {
      groupIndex: i + 1,
      slugs: g.slugs || [],
      instruction: g.instruction || "",
      status: "starting",
      retryAttempt: 0,
      activity: [],
    })
  })

  function ensureAgent(group: number, slugsLabel: string): AgentState {
    let agent = byGroup.get(group)
    if (!agent) {
      agent = {
        groupIndex: group,
        slugs: slugsLabel ? slugsLabel.split(", ").map((s) => s.trim()).filter(Boolean) : [],
        instruction: "",
        status: "starting",
        retryAttempt: 0,
        activity: [],
      }
      byGroup.set(group, agent)
    } else if (!agent.slugs.length && slugsLabel) {
      agent.slugs = slugsLabel.split(", ").map((s) => s.trim()).filter(Boolean)
    }
    return agent
  }

  let phase: ComposeState["phase"] = "running"
  let statusMessage: string | null = null
  let totalGroupsFromStream = 0

  for (const event of streamMessages) {
    const group = typeof event.group === "number" ? event.group : 0

    if (group === 0) {
      if (event.status === "prefetching") {
        phase = "prefetching"
        statusMessage = typeof event.message === "string" ? event.message : null
      } else if (event.status === "building") {
        phase = "building"
        statusMessage = typeof event.message === "string" ? event.message : null
      }
      continue
    }

    if (typeof event.total_groups === "number" && event.total_groups > totalGroupsFromStream) {
      totalGroupsFromStream = event.total_groups
    }

    const slugsLabel = typeof event.slugs === "string" ? event.slugs : ""
    const agent = ensureAgent(group, slugsLabel)

    if (event.status === "starting") {
      agent.status = "working"
      if (phase === "prefetching") {
        phase = "running"
        statusMessage = null
      }
    } else if (event.status === "retrying") {
      const retryError = typeof event.error === "string" ? event.error : agent.errorMsg
      if (retryError) agent.previousAttemptError = retryError
      agent.status = "retrying"
      agent.retryAttempt = typeof event.attempt === "number" ? event.attempt : agent.retryAttempt + 1
      agent.errorMsg = retryError
      agent.activity = []
    } else if (event.status === "done") {
      agent.status = "done"
      agent.errorMsg = undefined
    } else if (event.status === "error") {
      agent.status = "error"
      if (typeof event.error === "string") agent.errorMsg = event.error
    } else if (event.status === "budget_reached") {
      agent.budgetReached = true
    } else if (event.tool) {
      const toolName = String(event.tool)
      const toolUseId = String(event.toolUseId || "")
      const inputValue = event.input as Record<string, unknown> | undefined
      const eventStatus = event.status as string | undefined
      const existing = agent.activity.find((activity) => activity.toolUseId === toolUseId)

      if (!existing) {
        agent.activity.push({
          toolUseId,
          tool: toolName,
          label: activityLabel(toolName, inputValue, t),
          category: activityCategory(toolName),
          status: eventStatus === "error" ? "error" : eventStatus === "success" ? "success" : "active",
        })
      } else {
        if (eventStatus) existing.status = eventStatus === "error" ? "error" : "success"
        if (inputValue) existing.label = activityLabel(toolName, inputValue, t)
      }

      if (agent.status !== "done") agent.status = "working"
    }
  }

  const agents = [...byGroup.values()].sort((a, b) => a.groupIndex - b.groupIndex)
  const totalGroups = Math.max(agents.length, totalGroupsFromStream, slideGroups.length)
  const doneGroupCount = agents.filter((agent) => agent.status === "done").length

  if (phase === "running" && doneGroupCount === totalGroups && totalGroups > 0) phase = "done"

  return { phase, statusMessage, totalGroups, doneGroupCount, agents }
}
