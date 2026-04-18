// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * parseComposeState — Pure function: streamMessages → structured state.
 *
 * Input: events from compose_slides progress_q + tool input definition.
 * Output: overall + per-agent state for ComposeCard rendering.
 */

import { activityLabel } from "./activityLabel"

export interface ComposeActivity {
  toolUseId: string
  tool: string
  label: string
  status: "active" | "success" | "error"
}

export type AgentStatus = "starting" | "working" | "retrying" | "done" | "error"

export interface AgentState {
  groupIndex: number        // 1-based
  slugs: string[]
  instruction: string
  status: AgentStatus
  retryAttempt: number
  errorMsg?: string
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
): ComposeState {
  const slideGroups = (input?.slide_groups as SlideGroup[]) || []
  const totalGroups = slideGroups.length

  const agents: AgentState[] = slideGroups.map((g, i) => ({
    groupIndex: i + 1,
    slugs: g.slugs || [],
    instruction: g.instruction || "",
    status: "starting",
    retryAttempt: 0,
    activity: [],
  }))

  let phase: ComposeState["phase"] = "running"
  let statusMessage: string | null = null
  let doneGroupCount = 0

  for (const ev of streamMessages) {
    const g = typeof ev.group === "number" ? ev.group : 0

    // Global status events
    if (g === 0) {
      if (ev.status === "prefetching") { phase = "prefetching"; statusMessage = typeof ev.message === "string" ? ev.message : null }
      else if (ev.status === "building") { phase = "building"; statusMessage = typeof ev.message === "string" ? ev.message : null }
      continue
    }

    const agent = agents[g - 1]
    if (!agent) continue

    if (ev.status === "starting") {
      agent.status = "working"
    } else if (ev.status === "retrying") {
      agent.status = "retrying"
      agent.retryAttempt = typeof ev.attempt === "number" ? ev.attempt : agent.retryAttempt + 1
      if (typeof ev.error === "string") agent.errorMsg = ev.error
      agent.activity = []
    } else if (ev.status === "done") {
      agent.status = "done"
      doneGroupCount++
    } else if (ev.status === "error") {
      agent.status = "error"
      if (typeof ev.error === "string") agent.errorMsg = ev.error
    } else if (ev.tool) {
      const toolName = String(ev.tool)
      const toolUseId = String(ev.toolUseId || "")
      const inp = (ev.input as Record<string, unknown> | undefined)
      const existing = agent.activity.find((a) => a.toolUseId === toolUseId)
      if (!existing) {
        agent.activity.push({
          toolUseId,
          tool: toolName,
          label: activityLabel(toolName, inp),
          status: "active",
        })
      }
      if (agent.status === "starting") agent.status = "working"
    } else if (ev.toolResult) {
      const tid = String(ev.toolResult)
      const act = agent.activity.find((a) => a.toolUseId === tid)
      if (act) act.status = ev.toolStatus === "error" ? "error" : "success"
    }
  }

  if (phase === "running" && doneGroupCount === totalGroups && totalGroups > 0) {
    phase = "done"
  }

  return { phase, statusMessage, totalGroups, doneGroupCount, agents }
}
