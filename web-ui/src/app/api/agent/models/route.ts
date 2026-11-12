// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local chat model and effort (lib/local/acp-process.ts, "Models").
 *
 * GET `?sessionId=<chat's client id>` (optional): the chat's models — its live session's list,
 * model and effort, else the configured engine's last known list (acp-models.json) and no
 * current model; never starts kiro-cli. Without an id, the list alone (Settings → Model).
 *
 * PUT `{sessionId, model?, effort?}` (at least one of the two, nothing else), JSON from the same
 * site: an idle live session changes at once; otherwise the choice applies from the chat's next
 * message. Answers the chat's models after it; 400 `{error, code}` for a model or effort the
 * chat is not offered, 502 when kiro-cli refused the change.
 */
import { chooseSessionModel, getSessionModels } from "@/lib/local/acp-process"
import { rejectCrossSite } from "@/lib/local/requestGuard"
import { ModelChoiceError } from "@/lib/local/sessionErrors"

export const dynamic = "force-dynamic"

const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/
const MODEL_ID = /^[A-Za-z0-9._:/-]{1,128}$/
const EFFORT = /^[a-z]{1,32}$/

export async function GET(req: Request) {
  const sessionId = new URL(req.url).searchParams.get("sessionId")
  if (sessionId !== null && !SESSION_ID.test(sessionId)) return Response.json({ error: "invalid sessionId" }, { status: 400 })
  return Response.json(getSessionModels(sessionId ?? undefined))
}

const BODY_ERROR = "body must be {\"sessionId\": string, \"model\"?: string, \"effort\"?: string} with a model or an effort"

export async function PUT(req: Request) {
  const refused = rejectCrossSite(req, { requireJson: true })
  if (refused) return refused
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return Response.json({ error: BODY_ERROR }, { status: 400 })
  const { sessionId, model, effort, ...rest } = body as Record<string, unknown>
  const valid = Object.keys(rest).length === 0
    && typeof sessionId === "string" && SESSION_ID.test(sessionId)
    && (model === undefined || (typeof model === "string" && MODEL_ID.test(model)))
    && (effort === undefined || (typeof effort === "string" && EFFORT.test(effort)))
    && (model !== undefined || effort !== undefined)
  if (!valid) return Response.json({ error: BODY_ERROR }, { status: 400 })
  try {
    const view = await chooseSessionModel(sessionId as string, {
      ...(model !== undefined ? { model: model as string } : {}),
      ...(effort !== undefined ? { effort: effort as string } : {}),
    })
    return Response.json(view)
  } catch (error) {
    if (!(error instanceof ModelChoiceError)) throw error
    if (error.code === "model_not_changed") console.warn("[models] kiro-cli did not change the model: %s", error.message)
    return Response.json({ error: error.message, code: error.code }, { status: error.code === "model_not_changed" ? 502 : 400 })
  }
}
