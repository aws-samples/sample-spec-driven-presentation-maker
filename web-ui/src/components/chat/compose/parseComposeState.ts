// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * parseComposeState — Pure function: streamMessages → structured state.
 *
 * Input: events from compose_slides progress_q + tool input definition.
 * Output: overall + per-agent state for ComposeCard rendering.
 */

import { activityLabel, activityCategory, type ActivityCategory } from "./activityLabel"

export interface ComposeActivity {
  toolUseId: string
  tool: string
  label: string
  category: ActivityCategory
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
  const slideGroups = (input?.slide_groups as SlideGroup[] | undefined) || []

  // Discover agents from either input (if already present) or stream events.
  // Key by groupIndex (authoritative from backend); slugs may be missing on some events.
  const byGroup = new Map<number, AgentState>()

  // Seed from input if available
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

  // Helper: ensure an agent entry exists for a given group.
  function ensureAgent(g: number, slugsLabel: string): AgentState {
    let a = byGroup.get(g)
    if (!a) {
      a = {
        groupIndex: g,
        slugs: slugsLabel ? slugsLabel.split(", ").map((s) => s.trim()).filter(Boolean) : [],
        instruction: "",
        status: "starting",
        retryAttempt: 0,
        activity: [],
      }
      byGroup.set(g, a)
    } else if (!a.slugs.length && slugsLabel) {
      a.slugs = slugsLabel.split(", ").map((s) => s.trim()).filter(Boolean)
    }
    return a
  }

  let phase: ComposeState["phase"] = "running"
  let statusMessage: string | null = null
  let totalGroupsFromStream = 0
  let doneGroupCount = 0

  for (const ev of streamMessages) {
    const g = typeof ev.group === "number" ? ev.group : 0

    // Global status events
    if (g === 0) {
      if (ev.status === "prefetching") { phase = "prefetching"; statusMessage = typeof ev.message === "string" ? ev.message : null }
      else if (ev.status === "building") { phase = "building"; statusMessage = typeof ev.message === "string" ? ev.message : null }
      continue
    }

    if (typeof ev.total_groups === "number" && ev.total_groups > totalGroupsFromStream) {
      totalGroupsFromStream = ev.total_groups
    }

    const slugsLabel = typeof ev.slugs === "string" ? ev.slugs : ""
    const agent = ensureAgent(g, slugsLabel)

    if (ev.status === "starting") {
      agent.status = "working"
      // Once running, clear prefetching phase message
      if (phase === "prefetching") { phase = "running"; statusMessage = null }
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
      const evStatus = ev.status as string | undefined
      const existing = agent.activity.find((a) => a.toolUseId === toolUseId)
      if (!existing) {
        agent.activity.push({
          toolUseId,
          tool: toolName,
          label: activityLabel(toolName, inp),
          category: activityCategory(toolName),
          status: evStatus === "error" ? "error" : evStatus === "success" ? "success" : "active",
        })
      } else {
        if (evStatus) {
          // ChatPanel merges toolResult into the existing tool entry as status field.
          existing.status = evStatus === "error" ? "error" : "success"
        }
        if (inp) {
          // Input arrived after toolStart — refine label from generic placeholder.
          existing.label = activityLabel(toolName, inp)
        }
      }
      if (agent.status === "starting") agent.status = "working"
    }
  }

  const agents = [...byGroup.values()].sort((a, b) => a.groupIndex - b.groupIndex)
  const totalGroups = Math.max(agents.length, totalGroupsFromStream, slideGroups.length)

  if (phase === "running" && doneGroupCount === totalGroups && totalGroups > 0) {
    phase = "done"
  }

  return { phase, statusMessage, totalGroups, doneGroupCount, agents }
}
