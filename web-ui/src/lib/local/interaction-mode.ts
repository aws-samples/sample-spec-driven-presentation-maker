// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Interaction-mode token for the local ACP path.
 *
 * The Web UI's Spec / Vibe pick is an environment fact the orchestrator workflow
 * cannot know. The cloud agent passes it as a one-line system part
 * (agent/prompts/wiring/interaction_*.md); ACP agents have a single prompt file,
 * so here the same token is prepended to the first prompt of a fresh session.
 * The meaning of `dialogue` / `fast` is defined in the orchestrator workflow only,
 * as is the meaning of the `Current deck:`, `Continued from:` and
 * `Changed outside since your last turn:` lines.
 */
import type { SessionOrigin } from "./kiro-sessions.types"

const TOKEN: Record<string, "dialogue" | "fast"> = {
  vibe: "fast",
  spec: "dialogue",
}

export function interactionToken(mode: string | undefined): string | null {
  const t = TOKEN[mode ?? ""]
  return t ? `Interaction mode: ${t}` : null
}

/** Prepend the token to the first prompt of a new session; other prompts pass through. */
export function withInteractionMode(query: string, mode: string | undefined, isFirstPrompt: boolean): string {
  const token = interactionToken(mode)
  if (!token || !isFirstPrompt) return query
  return `${token}\n\n${query}`
}

export function continuedFromToken(origin: SessionOrigin): string {
  return `Continued from: kiro session ${JSON.stringify(origin.title)}`
}

/** Prepend the continuation fact only to the first prompt after a fork. */
export function withContinuedFrom(
  query: string,
  origin: SessionOrigin | undefined,
  isFirst: boolean,
): string {
  if (!origin || !isFirst) return query
  return `${continuedFromToken(origin)}\n\n${query}`
}

export function currentDeckToken(deckDir: string): string {
  return `Current deck: ${deckDir}`
}

/**
 * Prepend the deck's absolute directory to the first prompt of a new session on an existing
 * deck (one with no kiro session to resume), so the agent works on that deck.
 */
export function withCurrentDeck(query: string, deckDir: string | null | undefined, isFirst: boolean): string {
  if (!deckDir || !isFirst) return query
  return `${currentDeckToken(deckDir)}\n\n${query}`
}

/**
 * The deck files changed outside the chat since its last work period: the deck's absolute
 * directory, then one line per file (relative, `/`-separated) and the count of the ones not listed.
 */
export function changedOutsideToken(deckDir: string, files: string[], more: number): string {
  const lines = [`Changed outside since your last turn: ${deckDir}`, ...files.map((file) => `- ${file}`)]
  if (more > 0) lines.push(`- … and ${more} more ${more === 1 ? "file" : "files"}`)
  return lines.join("\n")
}
