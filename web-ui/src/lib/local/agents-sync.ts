// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * agents-sync — single implementation of the `.kiro/agents/` derivation.
 *
 * `.kiro/agents/` (what kiro-cli actually spawns) is a GENERATED directory:
 *
 *     agents/ = f(acp-agents/ catalog, acp-agent-selection.json, model)
 *
 * It is re-derived idempotently on every agent spawn (acp-process.ts) and on
 * Settings save (api/agent/definitions/route.ts), so a `git pull` that
 * updates the catalog is picked up by the next spawn — no stale copies.
 * Hand-edits to agents/ are therefore lost by design; the README marker
 * written alongside the files says so.
 */
import fs from "fs"
import path from "path"

const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")

export interface SyncDirs {
  acpAgentsDir: string
  agentsDir: string
  configPath: string
}

export const DEFAULT_DIRS: SyncDirs = {
  acpAgentsDir: path.join(MCP_LOCAL_DIR, ".kiro", "acp-agents"),
  agentsDir: path.join(MCP_LOCAL_DIR, ".kiro", "agents"),
  configPath: path.join(MCP_LOCAL_DIR, ".sdpm", "acp-agent-selection.json"),
}

/** Role → which agent JSON file is selected */
export interface AgentSelection {
  spec: string
  vibe: string
  composer: string
  single: string
  style: string
  model?: string
}

export const SELECTION_DEFAULTS: AgentSelection = {
  spec: "sdpm-spec.json",
  vibe: "sdpm-vibe.json",
  composer: "sdpm-composer.json",
  single: "sdpm-single.json",
  style: "sdpm-style.json",
}

/** Role → the fixed file name the ACP layer spawns (invoke route contract). */
const ROLE_TO_FIXED: Record<string, string> = {
  spec: "sdpm-spec.json",
  vibe: "sdpm-vibe.json",
  composer: "sdpm-composer.json",
  single: "sdpm-single.json",
  style: "sdpm-style.json",
}

const README_MARKER = `# Generated directory — do not hand-edit

Files here are re-derived from \`../acp-agents/\` (the catalog) combined with
\`.sdpm/acp-agent-selection.json\` (your Settings selection + model) on every
agent spawn and on Settings save. Any manual change is overwritten.

To change agent behavior, edit \`personas/*.md\`; to change wiring, edit the
catalog in \`../acp-agents/\`; to switch agents or model, use Settings.
`

/** Validate that a filename is a simple .json file (no path traversal). */
export function isSafeFileName(name: string): boolean {
  return /^[\w-]+\.json$/.test(name)
}

export function readSelection(dirs: SyncDirs = DEFAULT_DIRS): AgentSelection {
  try {
    if (fs.existsSync(dirs.configPath)) {
      return { ...SELECTION_DEFAULTS, ...JSON.parse(fs.readFileSync(dirs.configPath, "utf-8")) }
    }
  } catch {}
  return { ...SELECTION_DEFAULTS }
}

export function writeSelection(sel: AgentSelection, dirs: SyncDirs = DEFAULT_DIRS): void {
  fs.mkdirSync(path.dirname(dirs.configPath), { recursive: true })
  fs.writeFileSync(dirs.configPath, JSON.stringify(sel, null, 2) + "\n", "utf-8")
}

/**
 * Re-derive `.kiro/agents/` from the catalog + selection. Idempotent —
 * safe (and intended) to call on every spawn.
 */
export function syncToAgentsDir(
  sel: AgentSelection = readSelection(),
  dirs: SyncDirs = DEFAULT_DIRS,
): void {
  if (!fs.existsSync(dirs.acpAgentsDir)) return
  fs.mkdirSync(dirs.agentsDir, { recursive: true })
  for (const [role, fixedName] of Object.entries(ROLE_TO_FIXED)) {
    const fileName = sel[role as keyof AgentSelection] || SELECTION_DEFAULTS[role as keyof AgentSelection]
    if (!fileName || !isSafeFileName(fileName as string)) continue
    const srcFile = path.join(dirs.acpAgentsDir, fileName as string) // nosemgrep: path-join-resolve-traversal
    if (!fs.existsSync(srcFile)) continue
    const agent = JSON.parse(fs.readFileSync(srcFile, "utf-8"))
    if (sel.model) {
      agent.model = sel.model
    } else {
      delete agent.model
    }
    fs.writeFileSync(path.join(dirs.agentsDir, fixedName), JSON.stringify(agent, null, 2) + "\n")
  }
  fs.writeFileSync(path.join(dirs.agentsDir, "README.md"), README_MARKER)
}
