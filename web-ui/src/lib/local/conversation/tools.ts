// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The main session's tool cards: each tool call's name by its toolCallId, and the deck a tool
 * result names. The names come from `tool_start` / `tool_use`; a result is shown under the name
 * its call was given, else under the name the result's own update gave.
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

export class ToolTracker {
  private readonly names = new Map<string, string>()

  start(id: string, name: string): ChatEvent[] {
    this.names.set(id, name)
    return [data({ toolStart: { toolUseId: id, name } })]
  }

  use(id: string, name: string, input: Record<string, unknown>): ChatEvent[] {
    this.names.set(id, name)
    return [data({ toolUse: { toolUseId: id, name, input } })]
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
