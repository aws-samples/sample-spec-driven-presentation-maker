// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends prompt to sessionId-keyed kiro-cli process.
 * A session conflict (turn still running, or the session locked by another
 * kiro-cli process) is answered with 409 and a SessionConflict body; a kiro-cli
 * that does not answer its setup requests in time with 504 and code `agent_timeout`.
 * A reopened deck without a kiro session to load gets a new one (lib/local/sessionNotices.ts).
 * The process manager saves the session to a deck the turn creates (and a fork's origin with it),
 * whether or not this stream is still read.
 */
import {
  sendPrompt,
  createNewProcessFor,
  getBufferedEvents,
  hasProcess,
  getOrCreateProcess,
  pendingOrigins,
  readSessionFromDeck,
  saveSessionToDeck,
} from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"
import { withContinuedFrom, withInteractionMode } from "@/lib/local/interaction-mode"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"
import { rejectCrossSite } from "@/lib/local/requestGuard"
import { isSessionNotFound, sessionConflict } from "@/lib/local/sessionErrors"
import type { LocalSessionNoticeCode } from "@/lib/local/sessionNotices"
import { AgentTimeoutError, localTurnError } from "@/lib/local/turnErrors"

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
        // A fork must restore the copied history even if its preloaded process was evicted.
        await getOrCreateProcess(clientSessionId, agentName, { setMode: true, signal })
      } else if (deckId && deckId !== "new") {
        // Existing deck reopened after evict — restore the kiro session its .session names
        // (the client may still hold an earlier id for this page, e.g. the deck fallback id).
        // A deck with no session to load (made by an MCP client or Kiro CLI, or its kiro session
        // is gone) starts a new one, saved to .session, and the chat says the earlier
        // conversation is not carried over.
        const savedSessionId = readSessionFromDeck(deckId)
        let restored = false
        if (savedSessionId) {
          try {
            await getOrCreateProcess(clientSessionId, agentName, { signal, kiroSessionId: savedSessionId })
            restored = true
          } catch (error) {
            if (!isSessionNotFound(error)) throw error
            console.warn("[invoke] deck %s: kiro session %s not found, starting a new one", deckId, savedSessionId)
          }
        }
        if (!restored) {
          const ps = await createNewProcessFor(clientSessionId, agentName, { signal })
          saveSessionToDeck(deckId, ps.sessionId!)
          isFirstPrompt = true
          notice = "context_not_carried_over"
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
    prompted = await sendPrompt(clientSessionId, prompt, agentName, { notice })
  } catch (error) {
    const conflict = sessionConflict(error)
    if (conflict) return Response.json(conflict, { status: 409 })
    if (error instanceof AgentTimeoutError) {
      console.warn("[invoke] %s", error.message)
      return Response.json(localTurnError(error.code), { status: 504 })
    }
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
