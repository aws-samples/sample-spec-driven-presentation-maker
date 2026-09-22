// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local-mode client for listing and forking kiro-cli sessions. */

import { IS_LOCAL } from "@/lib/mode"
import type {
  ForkSessionRequest,
  ForkSessionResponse,
  KiroSessionsResponse,
} from "@/lib/local/kiro-sessions.types"

const EMPTY_SESSIONS: KiroSessionsResponse = { groups: [], recent: [] }

export async function listKiroSessions(includeAll = false, signal?: AbortSignal): Promise<KiroSessionsResponse> {
  if (!IS_LOCAL) return EMPTY_SESSIONS

  const response = await fetch(`/api/agent/sessions?all=${includeAll ? "1" : "0"}`, { signal })
  if (!response.ok) throw new Error(`Failed to list kiro sessions: ${response.status}`)
  return response.json() as Promise<KiroSessionsResponse>
}

export async function forkKiroSession(request: ForkSessionRequest): Promise<ForkSessionResponse> {
  if (!IS_LOCAL) throw new Error("kiro session forking is only available in Local mode")

  const response = await fetch("/api/agent/sessions/fork", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  })
  if (!response.ok) throw new Error(`Failed to fork kiro session: ${response.status}`)
  return response.json() as Promise<ForkSessionResponse>
}
