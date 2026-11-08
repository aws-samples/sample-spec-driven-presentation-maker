// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The conversation model of one Local chat, engine-independent: it turns the engine adapter's
 * `LocalEvent`s into the chat's `ChatEvent`s. It holds the turn's tool cards, its Compose cards
 * and the steers kiro-cli queued (a hidden one, the Local server's own text, is never reported);
 * the chat (chat.ts) numbers and buffers what it returns, ends the turn through `endTurn` before
 * its end events, and saves the deck a tool result names.
 *
 * The compose run's tools (`RUN_TOOLS`, recognised by the name their `tool_use` gave, never by a
 * `tool_end`'s): their calls are also returned as `runToolUses`, and their ends as `runToolEnds`
 * with no tool result, which the run answers (`toolResult`). Its task cards (`tasks`) live for the
 * work period, not the turn.
 */
import { ComposeTracker, TaskCards } from "./compose"
import { data, type ChatEvent, type LocalEvent, type ToolEndStatus } from "./events"
import { SteerQueue, steerEvent } from "./steer"
import { RUN_TOOLS, ToolTracker, withDeckId } from "./tools"

/** A call of one of the compose run's tools. */
export interface RunToolUse {
  id: string
  name: string
  input: Record<string, unknown>
}

/** Its end, as kiro-cli reported it. */
export interface RunToolEnd {
  id: string
  name: string
  status: ToolEndStatus
  result: Record<string, unknown>
}

export class ConversationState {
  readonly steers = new SteerQueue()
  /** The compose tasks' cards (never reset by a turn). */
  readonly tasks = new TaskCards()
  private tools = new ToolTracker()
  private compose = new ComposeTracker()

  /** A new turn: its tool cards and Compose card start empty (the steers are the turn's own). */
  beginTurn(): void {
    this.tools = new ToolTracker()
    this.compose = new ComposeTracker()
  }

  /**
   * The turn is over (before its end event): an open Compose card closes, its groups that did
   * not end failed.
   */
  endTurn(): ChatEvent[] {
    return this.compose.endTurn()
  }

  /** The name the current turn's `tool_use` gave call `id`. */
  toolNameOf(id: string): string | undefined {
    return this.tools.usedName(id)
  }

  /** A tool card's result (the compose run answers its tools' calls with it); `name` when the turn's tracker no longer knows the call. */
  toolResult(id: string, status: ToolEndStatus, result: Record<string, unknown>, name = ""): { events: ChatEvent[]; deckId?: string } {
    return this.tools.end(id, status, result, name)
  }

  /**
   * The chat events for one notification's LocalEvents, the deck a tool result named, and the
   * compose run's tool calls and ends, in event order.
   */
  apply(events: LocalEvent[]): { events: ChatEvent[]; deckId?: string; runToolUses: RunToolUse[]; runToolEnds: RunToolEnd[] } {
    const out: ChatEvent[] = []
    const runToolUses: RunToolUse[] = []
    const runToolEnds: RunToolEnd[] = []
    let deckId: string | undefined
    let composerBatch = false
    for (const event of events) {
      switch (event.type) {
        case "text":
          out.push(data({ event: { contentBlockDelta: { delta: { text: event.text } } } }))
          break
        case "tool_start":
          out.push(...this.tools.start(event.id, event.name))
          break
        case "tool_use":
          out.push(...this.tools.use(event.id, event.name, event.input))
          if (RUN_TOOLS.has(event.name)) runToolUses.push({ id: event.id, name: event.name, input: event.input })
          break
        case "tool_end": {
          const used = this.tools.usedName(event.id)
          if (this.compose.isDelegation(event.id)) {
            // The delegation's card ends with its groups (composer_end), not with its tool call.
            deckId ??= withDeckId(event.result).deckId
          } else if (used && RUN_TOOLS.has(used)) {
            runToolEnds.push({ id: event.id, name: used, status: event.status, result: event.result })
          } else {
            const ended = this.tools.end(event.id, event.status, event.result, event.name)
            out.push(...ended.events)
            deckId ??= ended.deckId
          }
          break
        }
        case "composer_start":
          // The notification's starts open (or extend) the card together, as one batch.
          if (!composerBatch) {
            composerBatch = true
            out.push(...this.compose.start(events.filter((e) => e.type === "composer_start")))
          }
          break
        case "composer_tool":
          out.push(...this.compose.tool(event.group, event.id, event.name))
          break
        case "composer_tool_end":
          out.push(...this.compose.toolEnd(event.group, event.id, event.status))
          break
        case "composer_end":
          out.push(...this.compose.groupEnd(event.group, event.status))
          break
        case "steer_injected": {
          const steer = this.steers.match(event)
          if (steer && !steer.hidden) out.push(steerEvent({ id: steer.id, state: "delivered" }))
          break
        }
        // mcp_status / mcp_snapshot: the host's MCP readiness watch (hosts.ts), not the chat.
        default:
          break
      }
    }
    return { events: out, ...(deckId ? { deckId } : {}), runToolUses, runToolEnds }
  }
}

export type { BufferedEvent, ChatEvent, LocalEvent, SsePayload } from "./events"
