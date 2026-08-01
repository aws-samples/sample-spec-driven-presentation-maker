// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Definitions API — lists available agent JSONs from acp-agents/
 * and reads/writes the user's per-role selection to acp-agent-selection.json.
 *
 * The `.kiro/agents/` derivation itself lives in lib/local/agents-sync.ts
 * (shared with the spawn path, which re-derives on every spawn).
 */
import fs from "fs"
import path from "path"

import {
  DEFAULT_DIRS,
  isSafeFileName,
  readSelection,
  syncToAgentsDir,
  writeSelection,
} from "@/lib/local/agents-sync"

export interface AgentDef {
  fileName: string
  name: string
  description: string
}

function listAgentDefs(): AgentDef[] {
  const dir = DEFAULT_DIRS.acpAgentsDir
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => {
      try {
        // f comes from readdirSync, not user input — safe
        const d = JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8")) // nosemgrep: path-join-resolve-traversal
        return { fileName: f, name: d.name || f.replace(".json", ""), description: d.description || "" }
      } catch {
        return { fileName: f, name: f.replace(".json", ""), description: "" }
      }
    })
}

/** GET: list available agents + current selection. Pure read — no side effects.
 *  agents/ re-derivation happens at spawn time (acp-process.ts). */
export async function GET() {
  return Response.json({
    agents: listAgentDefs(),
    selection: readSelection(),
  })
}

/** PUT: update selection and sync to agents/ */
export async function PUT(req: Request) {
  const body = await req.json()
  // Validate role values are safe filenames (model is a free-form model ID)
  for (const [k, v] of Object.entries(body)) {
    if (k === "model") continue
    if (typeof v === "string" && !isSafeFileName(v)) {
      return Response.json({ error: "Invalid filename" }, { status: 400 })
    }
  }
  const current = readSelection()
  const next = { ...current, ...body }
  // Derive first — a selection that cannot derive must not be persisted
  // (all-or-nothing: existing agents/ output is untouched on failure).
  try {
    syncToAgentsDir(next)
  } catch (e) {
    return Response.json({ error: String(e instanceof Error ? e.message : e) }, { status: 400 })
  }
  writeSelection(next)
  return Response.json({ ok: true, selection: next })
}
