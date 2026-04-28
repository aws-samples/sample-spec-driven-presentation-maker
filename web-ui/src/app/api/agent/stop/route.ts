// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Stop — cancel a specific deck's prompt.
 * newChat=true is a no-op (process is spawned on first invoke).
 */
import { cancelDeck } from "@/lib/local/acp-process"

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))

  if (body.newChat) {
    // No-op: new process will be spawned when user sends first message
    return Response.json({ ok: true })
  }

  if (body.deckId) {
    cancelDeck(body.deckId)
  }
  // Without deckId, do nothing — don't cancel all background processes
  return Response.json({ ok: true })
}
