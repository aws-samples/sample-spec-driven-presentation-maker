// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Chat Save/Load — persists chat messages to deck's .chat.json. A save with `delivered` (the
 * session id whose stream the page read to its end) delivers that work period once the messages
 * are written (acp-process.ts `markDelivered`): /api/agent/stream no longer replays it.
 */
import { markDelivered, saveChatToDeck, readChatFromDeck } from "@/lib/local/acp-process"
import { rejectCrossSite } from "@/lib/local/requestGuard"

export async function POST(req: Request) {
  const refused = rejectCrossSite(req)
  if (refused) return refused
  const { deckId, messages, delivered } = await req.json()
  if (!deckId || !messages) return Response.json({ error: "deckId and messages required" }, { status: 400 })
  if (saveChatToDeck(deckId, messages) && typeof delivered === "string" && delivered) markDelivered(delivered)
  return Response.json({ ok: true })
}

export async function GET(req: Request) {
  const deckId = new URL(req.url).searchParams.get("deckId")
  if (!deckId) return Response.json({ error: "deckId required" }, { status: 400 })
  return Response.json({ messages: readChatFromDeck(deckId) })
}
