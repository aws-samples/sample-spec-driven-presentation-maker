// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Steer — send a message into the session's running turn (lib/local/steer.ts).
 * Body `{sessionId, id, text}`; `id` is the chat's id for the message, which the turn's stream
 * then reports as `{steer: {id, state}}`. 200 `{steer: {id, state: "accepted"}}` once kiro-cli
 * queued it; 409 `{code, error}` when it did not (no turn running, not queued); 504
 * `agent_timeout` when kiro-cli did not answer.
 */
import { steerSession } from "@/lib/local/acp-process"
import { rejectCrossSite } from "@/lib/local/requestGuard"
import { SteerRejectedError } from "@/lib/local/steer"
import { AgentTimeoutError, localTurnError } from "@/lib/local/turnErrors"

export const dynamic = 'force-dynamic'

/** The chat sends a UUID; anything longer is not one of its ids. */
const MAX_ID_LENGTH = 100

export async function POST(req: Request) {
  const refused = rejectCrossSite(req, { requireJson: true })
  if (refused) return refused
  let body: { sessionId?: unknown; id?: unknown; text?: unknown }
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  const { sessionId, id, text } = body
  if (typeof sessionId !== "string" || !sessionId || typeof id !== "string" || !id || id.length > MAX_ID_LENGTH
    || typeof text !== "string" || !text.trim()) {
    return Response.json({ error: "sessionId, id and text required" }, { status: 400 })
  }
  try {
    await steerSession(sessionId, id, text)
  } catch (error) {
    if (error instanceof SteerRejectedError) return Response.json({ code: error.code, error: error.message }, { status: 409 })
    if (error instanceof AgentTimeoutError) {
      console.warn("[steer] %s", error.message)
      return Response.json(localTurnError(error.code), { status: 504 })
    }
    throw error
  }
  return Response.json({ steer: { id, state: "accepted" } })
}
