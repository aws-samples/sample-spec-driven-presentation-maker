// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Service — client for the Local-only Next.js API routes (`src/app/api/`):
 * open in the OS, chat persistence, agent stop and steer, the agent engine, agent definitions
 * and models. Every function returns early in cloud mode, where those routes do not exist.
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

/** A model of the chat's kiro session (`/api/agent/models`); names are kiro-cli's. */
export interface LocalModelOption {
  modelId: string
  name: string
  description?: string
  /** Only for a model with effort levels (V3). */
  effortLevels?: string[]
  defaultEffort?: string
  /** kiro-cli's credit multiplier (V3). */
  rate?: number
}

/** A change of the chat's model and/or effort. */
export interface LocalModelChoice {
  model?: string
  effort?: string
}

/** A chat's models: what its live session runs (null without one) and the choice for its next message. */
export interface LocalSessionModels {
  engine: AgentEngine
  available: LocalModelOption[]
  current: { model: string; effort: string | null; effortLevels: string[] } | null
  pending: LocalModelChoice | null
}

/** The kiro-cli engine that runs the sdpm agents (`/api/agent/engine`). */
export type AgentEngine = "v2" | "v3"

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
 * Send a message into a session's running turn (a steer, `/api/agent/steer`). The turn's
 * stream then reports it as `{steer: {id, state}}`.
 *
 * @param sessionId - Session whose turn runs
 * @param id - The chat's id for the message
 * @param text - The message
 * @throws Error (with the route's `code` when it has one) when kiro-cli did not accept it
 */
export async function steerLocalAgent(sessionId: string, id: string, text: string): Promise<void> {
  if (!IS_LOCAL) return
  const response = await fetch("/api/agent/steer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, id, text }),
  })
  if (response.ok) return
  const body = await response.text()
  const error = Object.assign(new Error(`Steer failed: ${response.status}: ${body}`), { code: undefined as unknown })
  try { error.code = JSON.parse(body).code } catch { /* non-JSON body */ }
  throw error
}

/**
 * Read which kiro-cli engine runs the sdpm agents.
 *
 * @returns The configured engine and the app's default (null in cloud mode)
 */
export async function getAgentEngine(): Promise<{ engine: AgentEngine; default: AgentEngine } | null> {
  if (!IS_LOCAL) return null
  const response = await fetch("/api/agent/engine")
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * Choose the kiro-cli engine for the sdpm agents; it takes effect from the next message.
 *
 * @param engine - `v3` or `v2`
 */
export async function setAgentEngine(engine: AgentEngine): Promise<void> {
  if (!IS_LOCAL) return
  await postJson("/api/agent/engine", { engine }, "PUT")
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
  // The last list a kiro-cli session reported; never starts one (empty until a session has).
  const response = await fetch("/api/agent/models")
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const data = await response.json()
  return (data.available || []).map((m: { modelId: string; name: string; description?: string }) => ({
    modelId: m.modelId, displayName: m.name, description: m.description,
  }))
}

/**
 * A chat's models: its live session's model and effort, the models it is offered, and the
 * choice that applies from its next message. Never starts kiro-cli.
 *
 * @param sessionId - The chat's session id (ChatPanel's)
 * @returns The chat's models, or null in cloud mode
 */
export async function getLocalSessionModels(sessionId: string): Promise<LocalSessionModels | null> {
  if (!IS_LOCAL) return null
  const response = await fetch(`/api/agent/models?sessionId=${encodeURIComponent(sessionId)}`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * Choose the chat's model and/or effort: at once when it is idle, else from its next message.
 *
 * @param sessionId - The chat's session id
 * @param choice - The model, the effort, or both
 * @returns The chat's models after the choice, or null in cloud mode
 */
export async function setLocalSessionModel(sessionId: string, choice: LocalModelChoice): Promise<LocalSessionModels | null> {
  if (!IS_LOCAL) return null
  const response = await postJson("/api/agent/models", { sessionId, ...choice }, "PUT")
  return response.json()
}
