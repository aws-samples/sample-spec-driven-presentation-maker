// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local agent engine — which kiro-cli engine runs the sdpm agents (lib/local/acp/engine-config.ts).
 * GET `{engine, default}`. PUT `{engine: "v2" | "v3"}` (nothing else) saves it to acp-config.json
 * and ends the idle deck processes of the other engine, so each deck's next message opens its
 * session on the new one; a running turn finishes on its engine first. 400 for another body,
 * 500 `{error}` when the file cannot be written.
 */
import { terminateIdleProcesses } from "@/lib/local/acp-process"
import { DEFAULT_ENGINE, isEngineId, readEngineConfig, writeEngine } from "@/lib/local/acp/engine-config"
import { rejectCrossSite } from "@/lib/local/requestGuard"

export const dynamic = "force-dynamic"

export async function GET() {
  return Response.json({ engine: readEngineConfig().engine, default: DEFAULT_ENGINE })
}

export async function PUT(req: Request) {
  const refused = rejectCrossSite(req, { requireJson: true })
  if (refused) return refused
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  const keys = typeof body === "object" && body !== null && !Array.isArray(body) ? Object.keys(body) : null
  const engine = (body as { engine?: unknown } | null)?.engine
  if (!keys || keys.length !== 1 || keys[0] !== "engine" || !isEngineId(engine)) {
    return Response.json({ error: "body must be {\"engine\": \"v2\" | \"v3\"}" }, { status: 400 })
  }
  try {
    writeEngine(engine)
  } catch (error) {
    console.error("[engine] could not save the agent engine: %s", error instanceof Error ? error.message : String(error))
    return Response.json({ error: "Could not save the agent engine setting" }, { status: 500 })
  }
  terminateIdleProcesses(engine)
  return Response.json({ ok: true, engine })
}
