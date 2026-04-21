// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Invoke — API Route that bridges kiro-cli acp to SSE.
 * Local mode only (`NEXT_PUBLIC_MODE=local`).
 */
import { ensureAgent, newSession, getSessionId, rpcRequest, subscribe, saveSessionToDeck } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"

export async function POST(req: Request) {
  const { query } = await req.json()

  await ensureAgent()

  const sessionId = getSessionId()!
  const stream = createSSEStream({
    sessionId,
    subscribe,
    onDeckId: (deckId) => saveSessionToDeck(deckId),
  })

  // Send prompt (don't await — response comes via notifications)
  rpcRequest("session/prompt", {
    sessionId,
    prompt: [{ type: "text", text: query }],
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
