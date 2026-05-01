// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Definitions API — lists available agent JSONs from acp-agents/
 * and reads/writes the user's per-role selection to acp-config.json.
 */
import fs from "fs"
import path from "path"

const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "mcp-local")
const ACP_AGENTS_DIR = path.join(MCP_LOCAL_DIR, ".kiro", "acp-agents")
const CONFIG_DIR = path.join(MCP_LOCAL_DIR, ".sdpm")
const CONFIG_PATH = path.join(CONFIG_DIR, "acp-agent-selection.json")

export interface AgentDef {
  fileName: string
  name: string
  description: string
}

/** Role → which agent JSON file is selected */
interface AgentSelection {
  spec: string
  vibe: string
  composer: string
  single: string
}

const DEFAULTS: AgentSelection = {
  spec: "sdpm-spec.json",
  vibe: "sdpm-vibe.json",
  composer: "sdpm-composer.json",
  single: "sdpm-single.json",
}

function readSelection(): AgentSelection {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      return { ...DEFAULTS, ...JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8")) }
    }
  } catch {}
  return { ...DEFAULTS }
}

function writeSelection(sel: AgentSelection): void {
  fs.mkdirSync(CONFIG_DIR, { recursive: true })
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(sel, null, 2) + "\n", "utf-8")
}

function listAgentDefs(): AgentDef[] {
  if (!fs.existsSync(ACP_AGENTS_DIR)) return []
  return fs.readdirSync(ACP_AGENTS_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => {
      try {
        const d = JSON.parse(fs.readFileSync(path.join(ACP_AGENTS_DIR, f), "utf-8"))
        return { fileName: f, name: d.name || f.replace(".json", ""), description: d.description || "" }
      } catch {
        return { fileName: f, name: f.replace(".json", ""), description: "" }
      }
    })
}

/** GET: list available agents + current selection */
export async function GET() {
  return Response.json({
    agents: listAgentDefs(),
    selection: readSelection(),
  })
}

/** PUT: update selection */
export async function PUT(req: Request) {
  const body = await req.json()
  const current = readSelection()
  const next = { ...current, ...body }
  writeSelection(next)
  return Response.json({ ok: true, selection: next })
}
