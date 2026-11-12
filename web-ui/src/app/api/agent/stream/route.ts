// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Stream — SSE endpoint with Last-Event-ID resume support (lib/local/acp-process.ts
 * `openStream`). A busy chat's work period is replayed after the given id (the whole period when
 * the header is not a non-negative integer), then streamed live; a finished period not delivered
 * yet (its tab was closed before it saved the chat) is replayed to its end, also after its chat
 * was released, until a page saves the chat after reading it (/api/agent/chat `delivered`).
 * `{running: false}` when there is nothing to stream.
 */
import { openStream } from "@/lib/local/acp-process"
import { createSSEStream } from "@/lib/local/sse-bridge"

export const dynamic = 'force-dynamic'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const sessionId = url.searchParams.get("sessionId")
  if (!sessionId) return Response.json({ error: "sessionId required" }, { status: 400 })

  const lastEventId = req.headers.get("Last-Event-ID")
  const afterId = lastEventId && /^\d+$/.test(lastEventId) ? Number(lastEventId) : undefined
  const opened = openStream(sessionId, afterId)
  if (!opened) return Response.json({ running: false })

  return new Response(createSSEStream(opened), {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
