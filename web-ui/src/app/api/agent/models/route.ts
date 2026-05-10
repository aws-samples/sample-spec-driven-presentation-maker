// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Model List/Select API.
 * Spawns a process if none exist (for initial model list).
 */
import { getModels, setConfigOption, createNewProcess } from "@/lib/local/acp-process"

export async function GET() {
  const models = getModels()
  if (!models.available.length) {
    await createNewProcess()
  }
  return Response.json(getModels())
}

export async function PUT(req: Request) {
  const { modelId, sessionId } = await req.json()
  if (sessionId) await setConfigOption(sessionId, "model", modelId)
  return Response.json({ ok: true })
}
