// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — sends prompt to sessionId-keyed kiro-cli process.
 */
import { sendPrompt, createNewProcessFor, hasProcess, getOrCreateProcess, saveSessionToDeck } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"
import { withInteractionMode } from "@/lib/local/interaction-mode"

const MODE_TO_AGENT: Record<string, string> = {
  vibe: "sdpm-orchestrator",
  spec: "sdpm-orchestrator",
  separated: "sdpm-orchestrator",
  single: "sdpm-orchestrator",
  style_creator: "sdpm-style",
  translate: "sdpm-translate",
}

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  const { query, mode, deckId, sessionId: clientSessionId } = await req.json()
  const agentName = MODE_TO_AGENT[mode || "spec"] || "sdpm-orchestrator"
  let isFirstPrompt = false

  // Ensure a process exists for this clientSessionId
  if (clientSessionId && !hasProcess(clientSessionId)) {
    if (deckId && deckId !== "new") {
      // Existing deck reopened after evict — restore via session/load
      await getOrCreateProcess(clientSessionId, agentName)
    } else {
      // Fresh session — spawn new process, register under client's sessionId
      await createNewProcessFor(clientSessionId, agentName)
      isFirstPrompt = true
    }
  } else if (!clientSessionId) {
    // No sessionId at all (shouldn't happen, but handle gracefully)
    await createNewProcessFor(crypto.randomUUID(), agentName)
    isFirstPrompt = true
  }

  // Spec / Vibe pick → one-line token defined by the orchestrator workflow
  const prompt = withInteractionMode(query, mode, isFirstPrompt)
  const { sessionId, subscribe, send } = await sendPrompt(clientSessionId!, prompt, agentName)

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
