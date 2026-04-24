// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Stop — cancel current prompt or reset session.
 * Local mode only.
 */
import { newSession, cancelAll, getSessionId } from "@/lib/local/acp-process"

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))

  if (body.newChat) {
    await newSession()
    return Response.json({ ok: true, sessionId: getSessionId() })
  }

  cancelAll()
  return Response.json({ ok: true })
}
