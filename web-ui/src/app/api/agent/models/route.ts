// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Model List/Select API — returns available models and sets the active model.
 * Local mode only.
 */
import { ensureAgent, getModels, setConfigOption } from "@/lib/local/acp-process"

export async function GET() {
  await ensureAgent()
  return Response.json(getModels())
}

export async function PUT(req: Request) {
  const { modelId } = await req.json()
  await ensureAgent()
  await setConfigOption("model", modelId)
  return Response.json({ ok: true })
}
