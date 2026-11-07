// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Compose card: a delegation to the composer, in the SSE shapes ComposeCard reads
 * (`toolUse compose_slides {slide_groups}`, `toolStream {group, slugs, ...}`, `toolResult`).
 *
 * - The first batch of `composer_start` events (one notification's worth) opens the card under
 *   the delegation's toolCallId with those groups as its `slide_groups`; each group then reports
 *   `starting`. A `composer_start` while the card is open adds a group, numbered in arrival order.
 * - `composer_tool` / `composer_tool_end` become the group's `tool` / `toolResult` stream events.
 * - The delegation's own `tool_end` closes the card with `toolResult compose_slides`.
 * - A group's slugs are read from its prompt; without any, the card shows "group N".
 */
import { data, type ChatEvent, type ComposeStreamData, type LocalEvent, type ToolEndStatus } from "./events"

const COMPOSE_TOOL = "compose_slides"

type ComposerStart = Extract<LocalEvent, { type: "composer_start" }>

interface Group {
  index: number
  slugs: string
}

/** The slugs a delegation prompt assigns (`slides: a, b`), or "" when it names none. */
export function extractSlugs(prompt: string): string {
  const m = prompt.match(/slides?:\s*([a-z0-9,\-\s]+?)(?:\.|$|\n)/i)
  return m ? m[1].trim() : ""
}

export class ComposeTracker {
  private card: { toolUseId: string; groups: Map<string, Group> } | null = null

  /** The open card's toolUseId, if any. */
  get toolUseId(): string | null {
    return this.card?.toolUseId ?? null
  }

  /** A batch of `composer_start` events from one notification. */
  start(batch: ComposerStart[]): ChatEvent[] {
    if (!batch.length) return []
    const events: ChatEvent[] = []
    if (!this.card) {
      this.card = { toolUseId: batch[0].toolCallId, groups: new Map() }
      const slideGroups = batch.map((start) => ({
        slugs: extractSlugs(start.prompt).split(", ").map((s) => s.trim()).filter(Boolean),
        instruction: start.prompt,
      }))
      events.push(data({ toolUse: { toolUseId: this.card.toolUseId, name: COMPOSE_TOOL, input: { slide_groups: slideGroups } } }))
    }
    const card = this.card
    const added = batch.filter((start) => !card.groups.has(start.group)).map((start) => {
      const index = card.groups.size + 1
      const group = { index, slugs: extractSlugs(start.prompt) || `group ${index}` }
      card.groups.set(start.group, group)
      return group
    })
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

  /** The delegation's tool call ended: close the card. */
  end(status: ToolEndStatus, result: Record<string, unknown>): ChatEvent[] {
    if (!this.card) return []
    const { toolUseId } = this.card
    this.card = null
    return [data({ toolResult: { toolUseId, name: COMPOSE_TOOL, status, content: JSON.stringify(result) } })]
  }

  private stream(streamData: ComposeStreamData): ChatEvent {
    return data({ toolStream: { toolUseId: this.card!.toolUseId, name: COMPOSE_TOOL, data: streamData } })
  }
}
