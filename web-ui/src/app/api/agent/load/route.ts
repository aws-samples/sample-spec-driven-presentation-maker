// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Session Load — restores an existing session.
 * Returns SSE stream of replayed history (session/update notifications).
 */
import { ensureAgent, loadSession, getSessionId, subscribe, readChatFromDeck } from "@/lib/local/acp-process"

export async function POST(req: Request) {
  const { sessionId: savedSessionId, deckId } = await req.json()
  if (!savedSessionId) return Response.json({ error: "sessionId required" }, { status: 400 })

  // Restore agent context (replay is ignored by client)
  await ensureAgent()
  await loadSession(savedSessionId)

  // Return saved chat messages
  const messages = deckId ? readChatFromDeck(deckId) : []
  return Response.json({ messages })
}
