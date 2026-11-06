// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends prompt to sessionId-keyed kiro-cli process.
 * A session conflict (turn still running, or the session locked by another
 * kiro-cli process) is answered with 409 and a SessionConflict body; a kiro-cli
 * that does not answer its setup requests in time with 504 and code `agent_timeout`;
 * one that cannot be made ready (lib/local/turnErrors.ts, AgentStartError) with 502 and its code.
 * A reopened deck whose session kiro-cli does not have, or that has none, gets a new one; a deck
 * whose session also ran on the other agent engine says so (lib/local/sessionNotices.ts).
 * The process manager saves the session to a deck the turn creates (and a fork's origin with it),
 * whether or not this stream is still read.
 */
import {
  sendPrompt,
  createNewProcessFor,
  getBufferedEvents,
  hasProcess,
  openDeckSession,
  openForkedSession,
  pendingOrigins,
  readSessionFromDeck,
} from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"
import { withContinuedFrom, withInteractionMode } from "@/lib/local/interaction-mode"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"
import { rejectCrossSite } from "@/lib/local/requestGuard"
import { sessionConflict } from "@/lib/local/sessionErrors"
import type { LocalSessionNoticeCode } from "@/lib/local/sessionNotices"
import { AgentStartError, AgentTimeoutError, localTurnError } from "@/lib/local/turnErrors"

const MODE_TO_AGENT: Record<string, string> = {
  vibe: "sdpm-orchestrator",
  spec: "sdpm-orchestrator",
  style_creator: "sdpm-style",
  translate: "sdpm-translate",
}

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  const refused = rejectCrossSite(req)
  if (refused) return refused
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
  let notice: LocalSessionNoticeCode | undefined
  if (clientSessionId && continuedFrom) pendingOrigins.set(clientSessionId, continuedFrom)

  let prompted: Awaited<ReturnType<typeof sendPrompt>>
  try {
    // Ensure a process exists for this clientSessionId. A client that goes away while
    // kiro-cli starts (or a kiro-cli that never answers) stops the spawn.
    const signal = req.signal
    if (clientSessionId && !hasProcess(clientSessionId)) {
      if (continuedFrom) {
        // A fork must restore the copied history even if its preloaded process was evicted. The
        // user already chats in it, so a copy kiro-cli could not read only gets the notice.
        const { outcome } = await openForkedSession(clientSessionId, agentName, { signal })
        if (outcome === "created") notice = "context_not_carried_over"
      } else if (deckId && deckId !== "new") {
        // Existing deck reopened after evict — open the kiro session its .session names (the
        // client may still hold an earlier id for this page, e.g. the deck fallback id). A deck
        // with no session to open (made by an MCP client or Kiro CLI, or its kiro session is gone)
        // continues in a new one, and the chat says the earlier conversation is not carried over.
        const { outcome, otherEngine } = await openDeckSession(clientSessionId, deckId, readSessionFromDeck(deckId), agentName, { signal })
        if (outcome === "created") {
          isFirstPrompt = true
          notice = "context_not_carried_over"
        } else if (otherEngine) {
          notice = "context_from_other_engine"
        }
      } else {
        // Fresh session — spawn new process, register under client's sessionId
        await createNewProcessFor(clientSessionId, agentName, { signal })
        isFirstPrompt = true
      }
    }

    // Spec / Vibe and continuation facts are attached only to the first prompt.
    const continuedPrompt = withContinuedFrom(query, continuedFrom, isFirstPrompt)
    const prompt = withInteractionMode(continuedPrompt, mode, isFirstPrompt)
    prompted = await sendPrompt(clientSessionId, prompt, { notice })
  } catch (error) {
    const conflict = sessionConflict(error)
    if (conflict) return Response.json(conflict, { status: 409 })
    if (error instanceof AgentTimeoutError) {
      console.warn("[invoke] %s", error.message)
      return Response.json(localTurnError(error.code), { status: 504 })
    }
    if (error instanceof AgentStartError) return Response.json(localTurnError(error.code), { status: 502 })
    // The client is gone; nobody reads this answer.
    if (req.signal.aborted) return new Response(null, { status: 499 })
    throw error
  }
  const { subscribe, send } = prompted

  // The turn's buffered events (its notice) first, then the live ones.
  const stream = createSSEStream({ subscribe, replay: getBufferedEvents(clientSessionId) })

  send()

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
