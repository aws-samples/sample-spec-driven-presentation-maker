// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Stop — cancel a specific session's prompt.
 * newChat=true is a no-op (process is spawned on first invoke).
 */
import { cancelSession, cancelAll } from "@/lib/local/acp-process"

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))

  if (body.newChat) {
    return Response.json({ ok: true })
  }

  if (body.sessionId) {
    cancelSession(body.sessionId)
  } else {
    cancelAll()
  }
  return Response.json({ ok: true })
}
