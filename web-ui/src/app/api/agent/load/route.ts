// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Session Load — restores an existing session.
 * Returns SSE stream of replayed history (session/update notifications).
 */
import { ensureAgent, loadSession, getSessionId, subscribe } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"

export async function POST(req: Request) {
  const { sessionId: savedSessionId } = await req.json()
  if (!savedSessionId) return Response.json({ error: "sessionId required" }, { status: 400 })

  await ensureAgent()
  await loadSession(savedSessionId)

  const sessionId = getSessionId()!
  const stream = createSSEStream({ sessionId, subscribe })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
