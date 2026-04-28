// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Session Load — restores chat history from disk.
 * Does NOT interact with kiro-cli to avoid interrupting background processes.
 */
import { readChatFromDeck } from "@/lib/local/acp-process"

export async function POST(req: Request) {
  const { sessionId: savedSessionId, deckId } = await req.json()
  if (!savedSessionId) return Response.json({ error: "sessionId required" }, { status: 400 })
  const messages = deckId ? readChatFromDeck(deckId) : []
  return Response.json({ messages })
}
