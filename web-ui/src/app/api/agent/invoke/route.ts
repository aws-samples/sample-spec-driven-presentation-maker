// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends prompt to sessionId-keyed kiro-cli process.
 */
import { sendPrompt, createNewProcessFor, hasProcess, getOrCreateProcess, saveSessionToDeck } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"

const MODE_TO_AGENT: Record<string, string> = {
  vibe: "sdpm-vibe",
  spec: "sdpm-spec",
  separated: "sdpm-spec",
  single: "sdpm-single",
  style_creator: "sdpm-style",
}

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  const { query, mode, deckId, sessionId: clientSessionId } = await req.json()
  const agentName = MODE_TO_AGENT[mode || "spec"] || "sdpm-spec"

  // Ensure a process exists for this clientSessionId
  if (clientSessionId && !hasProcess(clientSessionId)) {
    if (deckId && deckId !== "new") {
      // Existing deck reopened after evict — restore via session/load
      await getOrCreateProcess(clientSessionId, agentName)
    } else {
      // Fresh session — spawn new process, register under client's sessionId
      await createNewProcessFor(clientSessionId, agentName)
    }
  } else if (!clientSessionId) {
    // No sessionId at all (shouldn't happen, but handle gracefully)
    await createNewProcessFor(crypto.randomUUID(), agentName)
  }

  const { sessionId, subscribe, send } = await sendPrompt(clientSessionId!, query, agentName)

  const stream = createSSEStream({
    sessionId,
    subscribe,
    onDeckId: (createdDeckId) => {
      saveSessionToDeck(createdDeckId, sessionId)
    },
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
