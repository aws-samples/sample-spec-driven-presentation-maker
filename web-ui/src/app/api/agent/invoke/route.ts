// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends a prompt to the sessionId-keyed chat (lib/local/acp-process.ts)
 * and streams its work period from this turn on.
 * A session conflict (turn still running, or the session locked by another
 * kiro-cli process) is answered with 409 and a SessionConflict body; a kiro-cli
 * that does not answer its setup requests in time with 504 and code `agent_timeout`;
 * one that cannot be made ready (lib/local/turnErrors.ts, AgentStartError) with 502 and its code.
 * A reopened deck whose session kiro-cli does not have, or that has none, gets a new one whose
 * first prompt names the deck (`Current deck: <dir>`); a deck
 * whose session also ran on the other agent engine says so (lib/local/sessionNotices.ts).
 * The chat saves the session to a deck the turn creates (and a fork's origin with it),
 * whether or not this stream is still read. Stop for the session while its chat starts
 * (POST /api/agent/stop, from any tab) aborts the start: no prompt is sent, and the answer is a
 * stream that ends at once as stopped; a client that went away gets 499.
 */
import {
  beginStart,
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
import { resolveDeckDir } from "@/lib/local/deck-paths"
import { withContinuedFrom, withCurrentDeck, withInteractionMode } from "@/lib/local/interaction-mode"
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

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache",
  Connection: "keep-alive",
}

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
  let currentDeck: string | null = null
  if (clientSessionId && continuedFrom) pendingOrigins.set(clientSessionId, continuedFrom)

  let prompted: Awaited<ReturnType<typeof sendPrompt>>
  // A client that goes away while kiro-cli starts, or Stop for this session, stops the start.
  const start = beginStart(clientSessionId, req.signal)
  try {
    // Ensure a chat exists for this clientSessionId.
    const signal = start.signal
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
        // The new session's first prompt names the deck's directory, so the agent works on it.
        const { outcome, otherEngine } = await openDeckSession(clientSessionId, deckId, readSessionFromDeck(deckId), agentName, { signal })
        if (outcome === "created") {
          isFirstPrompt = true
          notice = "context_not_carried_over"
          currentDeck = resolveDeckDir(deckId)
        } else if (otherEngine) {
          notice = "context_from_other_engine"
        }
      } else {
        // A new chat, or one whose chat was released or whose kiro-cli exited: its kiro session is
        // opened again (`resumed`), and one kiro-cli no longer has starts over with the notice.
        const created = await createNewProcessFor(clientSessionId, agentName, { signal })
        if (!created.resumed) isFirstPrompt = true
        if (created.notice) notice = created.notice
      }
    }

    // Spec / Vibe, the current deck and continuation facts are attached only to the first prompt.
    const continuedPrompt = withContinuedFrom(query, continuedFrom, isFirstPrompt)
    const deckPrompt = withCurrentDeck(continuedPrompt, currentDeck, isFirstPrompt)
    const prompt = withInteractionMode(deckPrompt, mode, isFirstPrompt)
    prompted = await sendPrompt(clientSessionId, prompt, { notice, displayText: query, signal })
  } catch (error) {
    const conflict = sessionConflict(error)
    if (conflict) return Response.json(conflict, { status: 409 })
    // Stopped while starting: nothing was sent, the reply ends as stopped.
    if (start.stoppedByUser() && !req.signal.aborted) {
      return new Response(createSSEStream({ replay: [{ id: 1, event: { kind: "end", stopReason: "cancelled" } }] }), { headers: SSE_HEADERS })
    }
    if (error instanceof AgentTimeoutError) {
      console.warn("[invoke] %s", error.message)
      return Response.json(localTurnError(error.code), { status: 504 })
    }
    if (error instanceof AgentStartError) return Response.json(localTurnError(error.code), { status: 502 })
    // The client is gone; nobody reads this answer.
    if (req.signal.aborted) return new Response(null, { status: 499 })
    throw error
  } finally {
    start.end()
  }
  const { subscribe, send, replayFrom, onEnd } = prompted

  // The period's events from this turn on (its notice among them), then the live ones; a stream
  // that writes the period's end has delivered it (a closed tab's period is replayed by /stream).
  const stream = createSSEStream({ subscribe, replay: getBufferedEvents(clientSessionId, replayFrom - 1), onEnd })

  send()

  return new Response(stream, { headers: SSE_HEADERS })
}
