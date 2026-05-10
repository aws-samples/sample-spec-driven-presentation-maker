// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Chat Save/Load — persists chat messages to deck's .chat.json. */
import { saveChatToDeck, readChatFromDeck } from "@/lib/local/acp-process"

export async function POST(req: Request) {
  const { deckId, messages } = await req.json()
  if (!deckId || !messages) return Response.json({ error: "deckId and messages required" }, { status: 400 })
  saveChatToDeck(deckId, messages)
  return Response.json({ ok: true })
}

export async function GET(req: Request) {
  const deckId = new URL(req.url).searchParams.get("deckId")
  if (!deckId) return Response.json({ error: "deckId required" }, { status: 400 })
  return Response.json({ messages: readChatFromDeck(deckId) })
}
