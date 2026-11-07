// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Compose card: delegations to the composer, in the SSE shapes ComposeCard reads
 * (`toolUse compose_slides {slide_groups}`, `toolStream {group, total_groups, slugs, ...}`,
 * `toolResult compose_slides`). The rules are the same for every engine:
 *
 * - A batch of `composer_start` events (one notification's worth) while no card is open opens
 *   one under the delegation's toolCallId, with the batch's groups as its `slide_groups`.
 *   A `composer_start` while the card is open adds a group to it, numbered in arrival order.
 *   Each new group reports `starting`, `total_groups` the card's groups so far (its batch included).
 * - `composer_tool` / `composer_tool_end` become the group's `tool` / `toolResult` stream events,
 *   `composer_end` its `done` / `error` status.
 * - The card closes (`toolResult compose_slides`) once every group has ended; a start after that
 *   opens a new card. The delegation's own tool end shows nothing more.
 * - At the end of the turn an open card closes, its groups that did not end reported `error`,
 *   whatever ended the turn.
 * - A group's slugs come from its prompt's `assigned_slugs:` line (the orchestrator's delegation
 *   template, as a JSON list or comma-separated) or a legacy `slides: a, b`; without any, the
 *   card shows "group N".
 */
import { data, type ChatEvent, type ComposeStreamData, type LocalEvent, type ToolEndStatus } from "./events"

const COMPOSE_TOOL = "compose_slides"

type ComposerStart = Extract<LocalEvent, { type: "composer_start" }>

interface Group {
  index: number
  slugs: string
  ended: ToolEndStatus | null
}

interface Card {
  toolUseId: string
  groups: Map<string, Group>
}

const unquote = (slug: string) => slug.trim().replace(/^["'`]+|["'`]+$/g, "").trim()

/** The slugs a delegation prompt assigns, or [] when it names none. */
export function promptSlugs(prompt: string): string[] {
  const assigned = prompt.match(/^[ \t]*assigned_slugs:[ \t]*(.*)$/im)
  if (assigned) {
    const list = assigned[1].trim()
    if (list.startsWith("[")) {
      try {
        const parsed: unknown = JSON.parse(list)
        if (Array.isArray(parsed)) return parsed.filter((s): s is string => typeof s === "string").map(unquote).filter(Boolean)
      } catch { /* not JSON: read it as a comma-separated list */ }
    }
    return list.replace(/^\[|\]$/g, "").split(",").map(unquote).filter(Boolean)
  }
  const legacy = prompt.match(/slides?:\s*([a-z0-9,\-\s]+?)(?:\.|$|\n)/i)
  return legacy ? legacy[1].split(",").map(unquote).filter(Boolean) : []
}

export class ComposeTracker {
  private card: Card | null = null
  /** The toolCallIds of this turn's delegations: their tool ends belong to a card, not a tool card. */
  private readonly delegations = new Set<string>()

  /** Whether `toolCallId` is a delegation to the composer this tracker has seen. */
  isDelegation(toolCallId: string): boolean {
    return this.delegations.has(toolCallId)
  }

  /** A batch of `composer_start` events from one notification. */
  start(batch: ComposerStart[]): ChatEvent[] {
    if (!batch.length) return []
    for (const start of batch) this.delegations.add(start.toolCallId)
    const events: ChatEvent[] = []
    if (!this.card) {
      this.card = { toolUseId: batch[0].toolCallId, groups: new Map() }
      const slideGroups = batch.map((start) => ({ slugs: promptSlugs(start.prompt), instruction: start.prompt }))
      events.push(data({ toolUse: { toolUseId: this.card.toolUseId, name: COMPOSE_TOOL, input: { slide_groups: slideGroups } } }))
    }
    const card = this.card
    const added: Group[] = []
    for (const start of batch) {
      if (card.groups.has(start.group)) continue
      const index = card.groups.size + 1
      const group: Group = { index, slugs: promptSlugs(start.prompt).join(", ") || `group ${index}`, ended: null }
      card.groups.set(start.group, group)
      added.push(group)
    }
    for (const group of added) {
      events.push(this.stream({ group: group.index, total_groups: card.groups.size, slugs: group.slugs, status: "starting" }))
    }
    return events
  }

  tool(group: string, id: string, name: string): ChatEvent[] {
    const g = this.card?.groups.get(group)
    return g ? [this.stream({ group: g.index, slugs: g.slugs, tool: name, toolUseId: id })] : []
  }

  toolEnd(group: string, id: string, status: ToolEndStatus): ChatEvent[] {
    const g = this.card?.groups.get(group)
    return g ? [this.stream({ group: g.index, slugs: g.slugs, toolResult: id, toolStatus: status })] : []
  }

  /** A group ended; the card closes when it was the last one still running. */
  groupEnd(group: string, status: ToolEndStatus): ChatEvent[] {
    const g = this.card?.groups.get(group)
    if (!g || g.ended) return []
    const events = [this.ended(g, status)]
    if ([...this.card!.groups.values()].every((other) => other.ended)) events.push(...this.close())
    return events
  }

  /** The turn ended: close an open card, its groups that did not end failed. */
  endTurn(): ChatEvent[] {
    if (!this.card) return []
    const events = [...this.card.groups.values()].filter((g) => !g.ended).map((g) => this.ended(g, "error"))
    return [...events, ...this.close()]
  }

  private ended(group: Group, status: ToolEndStatus): ChatEvent {
    group.ended = status
    return this.stream({ group: group.index, slugs: group.slugs, status: status === "success" ? "done" : "error" })
  }

  private close(): ChatEvent[] {
    const card = this.card!
    this.card = null
    const status: ToolEndStatus = [...card.groups.values()].every((g) => g.ended === "success") ? "success" : "error"
    return [data({ toolResult: { toolUseId: card.toolUseId, name: COMPOSE_TOOL, status, content: "{}" } })]
  }

  private stream(streamData: ComposeStreamData): ChatEvent {
    return data({ toolStream: { toolUseId: this.card!.toolUseId, name: COMPOSE_TOOL, data: streamData } })
  }
}
