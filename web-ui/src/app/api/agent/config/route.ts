// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Config — CRUD for agent adapters.
 * Bridges AgentSettingsDialog (client) ↔ acp-adapter (server-side JSON).
 */
import { getAgents, getActiveAgentId, setActiveAgentId, saveAgents } from "@/lib/local/acp-adapter"

/** GET: list agents + active ID */
export async function GET() {
  return Response.json({
    agents: getAgents(),
    activeAgent: getActiveAgentId(),
  })
}

/** PUT: update agents list and/or active agent */
export async function PUT(req: Request) {
  const body = await req.json()
  if (body.agents) saveAgents(body.agents)
  if (body.activeAgent) setActiveAgentId(body.activeAgent)
  return Response.json({ ok: true })
}
