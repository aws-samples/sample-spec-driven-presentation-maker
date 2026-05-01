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

const ROLE_TO_FIXED: Record<string, string> = {
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

/** Validate that a filename is a simple .json file (no path traversal). */
function isSafeFileName(name: string): boolean {
  return /^[\w-]+\.json$/.test(name)
}

/** Copy selected agents to .kiro/agents/ with fixed names. */
function syncToAgentsDir(sel: AgentSelection): void {
  const dest = path.join(MCP_LOCAL_DIR, ".kiro", "agents")
  fs.mkdirSync(dest, { recursive: true })
  for (const [role, fixedName] of Object.entries(ROLE_TO_FIXED)) {
    const fileName = sel[role as keyof AgentSelection] || DEFAULTS[role as keyof AgentSelection]
    if (!isSafeFileName(fileName)) continue
    const srcFile = path.join(ACP_AGENTS_DIR, fileName) // nosemgrep: path-join-resolve-traversal
    if (fs.existsSync(srcFile)) {
      fs.copyFileSync(srcFile, path.join(dest, fixedName))
    }
  }
}

function listAgentDefs(): AgentDef[] {
  if (!fs.existsSync(ACP_AGENTS_DIR)) return []
  return fs.readdirSync(ACP_AGENTS_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => {
      try {
        // f comes from readdirSync, not user input — safe
        const d = JSON.parse(fs.readFileSync(path.join(ACP_AGENTS_DIR, f), "utf-8")) // nosemgrep: path-join-resolve-traversal
        return { fileName: f, name: d.name || f.replace(".json", ""), description: d.description || "" }
      } catch {
        return { fileName: f, name: f.replace(".json", ""), description: "" }
      }
    })
}

/** GET: list available agents + current selection. Pure read — no side effects.
 *  agents/ bootstrap is handled by ensureAgentsDir() at spawn time. */
export async function GET() {
  return Response.json({
    agents: listAgentDefs(),
    selection: readSelection(),
  })
}

/** PUT: update selection and sync to agents/ */
export async function PUT(req: Request) {
  const body = await req.json()
  // Validate all values are safe filenames
  for (const v of Object.values(body)) {
    if (typeof v === "string" && !isSafeFileName(v)) {
      return Response.json({ error: "Invalid filename" }, { status: 400 })
    }
  }
  const current = readSelection()
  const next = { ...current, ...body }
  writeSelection(next)
  syncToAgentsDir(next)
  return Response.json({ ok: true, selection: next })
}
