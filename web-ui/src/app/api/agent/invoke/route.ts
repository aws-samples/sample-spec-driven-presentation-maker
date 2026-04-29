// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends prompt to deck-specific kiro-cli process.
 * Each deck gets its own process; switching decks doesn't interrupt others.
 */
import { sendPrompt, newProcess, associateDeck, saveSessionToDeck } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"

const MODE_TO_AGENT: Record<string, string> = {
  vibe: "sdpm-vibe",
  spec: "sdpm-spec",
  separated: "sdpm-spec",
  single: "sdpm-spec",
}

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  const { query, mode, deckId } = await req.json()
  const agentName = MODE_TO_AGENT[mode || "spec"] || "sdpm-spec"

  let effectiveDeckId: string
  let tempKey: string | null = null

  if (deckId && deckId !== "new") {
    effectiveDeckId = deckId
  } else {
    // New deck — spawn process with temp key
    const { tempKey: tk } = await newProcess(agentName)
    tempKey = tk
    effectiveDeckId = tk
  }

  const { sessionId, subscribe, send } = await sendPrompt(effectiveDeckId, query, agentName)

  // Create SSE stream (registers listener) BEFORE sending prompt
  const stream = createSSEStream({
    sessionId,
    subscribe,
    onDeckId: (createdDeckId) => {
      if (tempKey) {
        associateDeck(tempKey, createdDeckId)
        tempKey = null
      }
      saveSessionToDeck(createdDeckId)
    },
    // onDone intentionally omitted — SSE close happens when browser navigates away,
    // not when agent finishes. running=false is set by handleLine on end_turn.
  })

  // Now send the prompt — listener is already registered
  send()

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
