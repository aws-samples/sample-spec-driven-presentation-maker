// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Stream — SSE endpoint with Last-Event-ID resume support.
 * Replays buffered events after the given ID, then streams live.
 */
import { isSessionRunning, getBufferedEvents, subscribeToSession } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"

export const dynamic = 'force-dynamic'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const sessionId = url.searchParams.get("sessionId")
  if (!sessionId) return Response.json({ error: "sessionId required" }, { status: 400 })

  if (!isSessionRunning(sessionId)) {
    return Response.json({ running: false })
  }

  const sub = subscribeToSession(sessionId)
  if (!sub?.sessionId) return Response.json({ running: false })

  const lastEventId = req.headers.get("Last-Event-ID")
  const afterId = lastEventId ? parseInt(lastEventId, 10) : undefined
  const buffered = getBufferedEvents(sessionId, afterId)

  const stream = createSSEStream({
    sessionId: sub.sessionId,
    subscribe: sub.subscribe,
    replay: buffered,
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
