// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends prompt to sessionId-keyed kiro-cli process.
 */
import {
  sendPrompt,
  createNewProcessFor,
  hasProcess,
  getOrCreateProcess,
  pendingOrigins,
  saveOriginToDeck,
  saveSessionToDeck,
} from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"
import { withContinuedFrom, withInteractionMode } from "@/lib/local/interaction-mode"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"

const MODE_TO_AGENT: Record<string, string> = {
  vibe: "sdpm-orchestrator",
  spec: "sdpm-orchestrator",
  style_creator: "sdpm-style",
  translate: "sdpm-translate",
}

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  let body: {
    query?: unknown
    mode?: string
    deckId?: string
    sessionId?: string
    continuedFrom?: SessionOrigin
  }
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  const {
    query,
    mode,
    deckId,
    sessionId: clientSessionId,
    continuedFrom,
  } = body
  if (typeof query !== "string" || !clientSessionId) {
    return Response.json({ error: "query and sessionId required" }, { status: 400 })
  }
  const agentName = MODE_TO_AGENT[mode || "spec"] || "sdpm-orchestrator"
  let isFirstPrompt = Boolean(continuedFrom)
  if (clientSessionId && continuedFrom) pendingOrigins.set(clientSessionId, continuedFrom)

  // Ensure a process exists for this clientSessionId
  if (clientSessionId && !hasProcess(clientSessionId)) {
    if (continuedFrom) {
      // A fork must restore the copied history even if its preloaded process was evicted.
      await getOrCreateProcess(clientSessionId, agentName, { setMode: true })
    } else if (deckId && deckId !== "new") {
      // Existing deck reopened after evict — restore via session/load
      await getOrCreateProcess(clientSessionId, agentName)
    } else {
      // Fresh session — spawn new process, register under client's sessionId
      await createNewProcessFor(clientSessionId, agentName)
      isFirstPrompt = true
    }
  }

  // Spec / Vibe and continuation facts are attached only to the first prompt.
  const continuedPrompt = withContinuedFrom(query, continuedFrom, isFirstPrompt)
  const prompt = withInteractionMode(continuedPrompt, mode, isFirstPrompt)
  const { sessionId, subscribe, send } = await sendPrompt(clientSessionId!, prompt, agentName)

  const stream = createSSEStream({
    sessionId,
    subscribe,
    onDeckId: (createdDeckId) => {
      saveSessionToDeck(createdDeckId, sessionId)
      const origin = pendingOrigins.get(sessionId)
      if (origin) {
        saveOriginToDeck(createdDeckId, origin)
        pendingOrigins.delete(sessionId)
      }
    },
    onError: () => pendingOrigins.delete(sessionId),
  })

  send()

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
