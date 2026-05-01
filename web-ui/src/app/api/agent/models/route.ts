// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Model List/Select API.
 * Spawns a process if none exist (for initial model list).
 */
import { getModels, setConfigOption, getActiveDeckId, newProcess } from "@/lib/local/acp-process"

export async function GET() {
  const models = getModels()
  if (!models.available.length) {
    // No process yet — spawn one so model list is populated
    await newProcess()
  }
  return Response.json(getModels())
}

export async function PUT(req: Request) {
  const { modelId } = await req.json()
  const deckId = getActiveDeckId()
  if (deckId) await setConfigOption(deckId, "model", modelId)
  return Response.json({ ok: true })
}
