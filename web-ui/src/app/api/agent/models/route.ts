// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Model List/Select API.
 * The model list comes from a kiro-cli session, so listing may have to start one: POST does
 * that when no process has reported models yet. GET only reads what is already known.
 */
import { getModels, setConfigOption, createNewProcess } from "@/lib/local/acp-process"
import { rejectCrossSite } from "@/lib/local/requestGuard"

/** GET: the models known so far (empty until a process has started). No side effects. */
export async function GET() {
  return Response.json(getModels())
}

/** POST: the model list, starting a process first when none has reported one yet. */
export async function POST(req: Request) {
  const refused = rejectCrossSite(req, { requireJson: true })
  if (refused) return refused
  if (!getModels().available.length) {
    await createNewProcess()
  }
  return Response.json(getModels())
}

export async function PUT(req: Request) {
  const refused = rejectCrossSite(req, { requireJson: true })
  if (refused) return refused
  const { modelId, sessionId } = await req.json()
  if (sessionId) await setConfigOption(sessionId, "model", modelId)
  return Response.json({ ok: true })
}
