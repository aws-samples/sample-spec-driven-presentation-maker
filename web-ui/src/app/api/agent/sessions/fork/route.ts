// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Fork a kiro-cli session and load it with the selected SDPM agent mode. */
import { getOrCreateProcess, pendingOrigins } from "@/lib/local/acp-process"
import { forkSession, removeForkedSession } from "@/lib/local/kiro-sessions"
import type { ForkSessionRequest } from "@/lib/local/kiro-sessions.types"

export const dynamic = "force-dynamic"

export async function POST(req: Request) {
  let body: Partial<ForkSessionRequest>
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  if (!body.sourceSessionId || !body.clientSessionId) {
    return Response.json({ error: "sourceSessionId and clientSessionId required" }, { status: 400 })
  }

  let fork: Awaited<ReturnType<typeof forkSession>>
  try {
    fork = await forkSession(body.sourceSessionId)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    const message = error instanceof Error ? error.message : "failed to fork session"
    const status = message.includes("invalid kiro session ID") ? 400 : code === "ENOENT" ? 404 : 500
    return Response.json({ error: message }, { status })
  }

  try {
    await getOrCreateProcess(fork.newId, body.agentName || "sdpm-orchestrator", { setMode: true })
    pendingOrigins.set(fork.newId, fork.origin)
    return Response.json({ sessionId: fork.newId, origin: fork.origin })
  } catch (error) {
    await removeForkedSession(fork.newId)
    const message = error instanceof Error ? error.message : "failed to load forked session"
    return Response.json({ error: message }, { status: 502 })
  }
}
