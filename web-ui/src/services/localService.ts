// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Service — client for the Local-only Next.js API routes (`src/app/api/`):
 * open in the OS, chat persistence, agent stop, agent definitions, models, and the
 * reconnect stream. Every function returns early in cloud mode, where those routes
 * do not exist.
 */

import { IS_LOCAL } from "@/lib/mode"

/** One agent JSON under acp-agents/. */
export interface AgentDefinition {
  fileName: string
  name: string
  description: string
}

/** Agent file chosen per role, plus the optional model override. */
export interface AgentSelection {
  orchestrator: string
  composer: string
  style: string
  translate: string
  model?: string
}

/** A model the local agent offers, in the shape ModelPicker takes. */
export interface LocalModel {
  modelId: string
  displayName: string
  description?: string
}

const EMPTY_SELECTION: AgentSelection = { orchestrator: "", composer: "", style: "", translate: "" }

async function postJson(url: string, body: unknown, method = "POST"): Promise<Response> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response
}

/**
 * Open a deck folder, or a file inside it, with the OS default handler.
 *
 * @param deckId - Deck identifier
 * @param file - File name inside the deck folder (e.g. "output.pptx"); omit to open the folder
 * @throws Error when the request fails or the route answers with an error status
 */
export async function openInOs(deckId: string, file?: string): Promise<void> {
  if (!IS_LOCAL) return
  await postJson("/api/open", { deckId, file })
}

/**
 * Write a deck's (or style's) chat messages to its `.chat.json`.
 *
 * @param deckId - Deck or style identifier the chat belongs to
 * @param messages - Messages in the chat panel's own format
 */
export async function saveLocalChat(deckId: string, messages: unknown[]): Promise<void> {
  if (!IS_LOCAL) return
  await postJson("/api/agent/chat", { deckId, messages })
}

/**
 * Cancel the running prompt of a session, or tell the server a new chat starts.
 *
 * @param target - `{ sessionId }` to cancel that session, `{ newChat: true }` for a new chat
 */
export async function stopLocalAgent(target: { sessionId: string } | { newChat: true }): Promise<void> {
  if (!IS_LOCAL) return
  await postJson("/api/agent/stop", target)
}

/**
 * List the agent definitions and the current per-role selection.
 *
 * @returns Available agents and the selection (empty in cloud mode)
 */
export async function getAgentDefinitions(): Promise<{ agents: AgentDefinition[]; selection: AgentSelection }> {
  if (!IS_LOCAL) return { agents: [], selection: EMPTY_SELECTION }
  const response = await fetch("/api/agent/definitions")
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const data = await response.json()
  return { agents: data.agents || [], selection: data.selection || {} }
}

/**
 * Update part of the agent selection (a role's agent file, or `model`; null clears the model).
 *
 * @param patch - Fields to change
 */
export async function updateAgentSelection(patch: Partial<Record<keyof AgentSelection, string | null>>): Promise<void> {
  if (!IS_LOCAL) return
  await postJson("/api/agent/definitions", patch, "PUT")
}

/**
 * List the models the local agent offers.
 *
 * @returns Models (empty in cloud mode)
 */
export async function listLocalModels(): Promise<LocalModel[]> {
  if (!IS_LOCAL) return []
  const response = await fetch("/api/agent/models")
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const data = await response.json()
  return (data.available || []).map((m: { modelId: string; name: string; description?: string }) => ({
    modelId: m.modelId, displayName: m.name, description: m.description,
  }))
}

function streamPath(sessionId: string): string {
  return `/api/agent/stream?sessionId=${encodeURIComponent(sessionId)}`
}

/**
 * URL of a session's server-sent event stream (replay + live).
 *
 * @param sessionId - ACP session identifier
 * @returns The stream URL, or null in cloud mode
 */
export function localStreamUrl(sessionId: string): string | null {
  if (!IS_LOCAL) return null
  return streamPath(sessionId)
}

/**
 * Whether a session is still running in the background (its stream answers with SSE).
 * The probe's body is cancelled right away; reconnect with an EventSource on localStreamUrl.
 *
 * @param sessionId - ACP session identifier
 * @returns True when the session streams; false otherwise, on error, and in cloud mode
 */
export async function hasLocalStream(sessionId: string): Promise<boolean> {
  if (!IS_LOCAL) return false
  try {
    const check = await fetch(streamPath(sessionId))
    const ct = check.headers.get("content-type") || ""
    try { check.body?.getReader()?.cancel() } catch {}
    return ct.includes("text/event-stream")
  } catch {
    return false
  }
}
