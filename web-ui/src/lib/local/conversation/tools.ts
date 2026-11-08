// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The main session's tool cards: each tool call's name by its toolCallId, and the deck a tool
 * result names. The names come from `tool_start` / `tool_use`; a result is shown under the name
 * its call was given, else under the name the result's own update gave. The name a call's
 * `tool_use` gave is kept apart (`usedName`): it is the only reliable one (V2's `tool_start` and
 * result names are titles, V3's MCP results have none), and it tells the compose run's tools.
 */
import path from "path"

import { DECK_ROOT } from "../deck-paths"
import { basename } from "../pathUtils"
import { data, type ChatEvent, type ToolEndStatus } from "./events"

const DECK_ROOT_ABS = path.resolve(DECK_ROOT)

/**
 * The deck a tool result names: its `deckId`, else the last segment of its `output_dir`. A deck's
 * output_dir is a child of the deck root; the root itself (start_presentation's output_dir) is
 * not a deck. The server reports normalized absolute paths. The returned result carries the
 * `deckId` it was given, as the chat shows it.
 */
export function withDeckId(result: Record<string, unknown>): { result: Record<string, unknown>; deckId?: string } {
  let shown = result
  if (result.output_dir && !result.deckId && String(result.output_dir).replace(/[\\/]+$/, "") !== DECK_ROOT_ABS) {
    shown = { ...result, deckId: basename(result.output_dir as string) }
  }
  return shown.deckId ? { result: shown, deckId: String(shown.deckId) } : { result: shown }
}

/** The tools whose results the compose run (compose-run.ts) answers instead of the tool card. */
export const RUN_TOOLS: ReadonlySet<string> = new Set(["compose_slides", "message_composer"])

export class ToolTracker {
  private readonly names = new Map<string, string>()
  /** The name each call's `tool_use` gave (only `use` writes it). */
  private readonly used = new Map<string, string>()

  start(id: string, name: string): ChatEvent[] {
    this.names.set(id, name)
    return [data({ toolStart: { toolUseId: id, name } })]
  }

  use(id: string, name: string, input: Record<string, unknown>): ChatEvent[] {
    this.names.set(id, name)
    this.used.set(id, name)
    return [data({ toolUse: { toolUseId: id, name, input } })]
  }

  /** The name the call's `tool_use` gave, if it had one. */
  usedName(id: string): string | undefined {
    return this.used.get(id)
  }

  end(id: string, status: ToolEndStatus, result: Record<string, unknown>, fallbackName = ""): { events: ChatEvent[]; deckId?: string } {
    const shown = withDeckId(result)
    const name = this.names.get(id) ?? fallbackName
    return {
      events: [data({ toolResult: { toolUseId: id, name, status, content: JSON.stringify(shown.result) } })],
      ...(shown.deckId ? { deckId: shown.deckId } : {}),
    }
  }
}
