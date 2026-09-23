// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local-mode client for listing and forking kiro-cli sessions. */

import { IS_LOCAL } from "@/lib/mode"
import type {
  ForkSessionPhase,
  ForkSessionPhaseDetail,
  ForkSessionRequest,
  ForkSessionResponse,
  KiroSessionsResponse,
} from "@/lib/local/kiro-sessions.types"

const EMPTY_SESSIONS: KiroSessionsResponse = { groups: [], recent: [] }

export interface ForkKiroSessionOptions {
  onPhase?: (phase: ForkSessionPhase, detail?: ForkSessionPhaseDetail) => void
  signal?: AbortSignal
}

export async function listKiroSessions(includeAll = false, signal?: AbortSignal): Promise<KiroSessionsResponse> {
  if (!IS_LOCAL) return EMPTY_SESSIONS

  const response = await fetch(`/api/agent/sessions?all=${includeAll ? "1" : "0"}`, { signal })
  if (!response.ok) throw new Error(`Failed to list kiro sessions: ${response.status}`)
  return response.json() as Promise<KiroSessionsResponse>
}

export async function forkKiroSession(
  request: ForkSessionRequest,
  options: ForkKiroSessionOptions = {},
): Promise<ForkSessionResponse> {
  if (!IS_LOCAL) throw new Error("kiro session forking is only available in Local mode")

  const response = await fetch("/api/agent/sessions/fork", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options.signal,
  })
  if (!response.ok) {
    const detail = await response.json().then((body: { error?: string }) => body.error).catch(() => undefined)
    throw new Error(`Failed to fork kiro session: ${response.status}${detail ? ` — ${detail}` : ""}`)
  }
  if (!response.body) throw new Error("Failed to fork kiro session: empty response stream")

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let result: ForkSessionResponse | undefined

  function processEvent(block: string) {
    let eventName = "message"
    const dataLines: string[] = []
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim()
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart())
    }
    if (dataLines.length === 0) return

    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>
    if (eventName === "phase") {
      const phase = data.phase
      if (phase === "copying" || phase === "starting" || phase === "loading" || phase === "switching") {
        options.onPhase?.(phase, typeof data.replayed === "number" ? { replayed: data.replayed } : undefined)
      }
      return
    }
    if (eventName === "done") {
      result = data as unknown as ForkSessionResponse
      return
    }
    if (eventName === "error") {
      const code = typeof data.code === "number" ? ` (${data.code})` : ""
      throw new Error(`Failed to fork kiro session${code}: ${String(data.error || "unknown error")}`)
    }
  }

  function drainEvents(final = false) {
    buffer = buffer.replace(/\r\n/g, "\n")
    let boundary = buffer.indexOf("\n\n")
    while (boundary >= 0) {
      processEvent(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf("\n\n")
    }
    if (final && buffer.trim()) {
      processEvent(buffer)
      buffer = ""
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    drainEvents()
  }
  buffer += decoder.decode()
  drainEvents(true)

  if (!result) throw new Error("Failed to fork kiro session: stream ended before completion")
  return result
}
