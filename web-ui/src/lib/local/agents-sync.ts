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
 *
 * All-or-nothing: every selected definition is loaded and validated in
 * memory first; if any source is missing or malformed, an Error is thrown
 * and the existing output is left untouched (the caller decides whether to
 * fail the spawn — spawning from silently stale files is the exact bug
 * this module exists to prevent). On success the directory is replaced
 * transactionally (staged in a sibling temp dir, old output moved to a
 * backup and restored if the swap fails), so a failure can never leave a
 * mix of old and new generations — or no directory at all — and stale
 * files from removed catalog entries are swept away.
 */
export function syncToAgentsDir(
  sel: AgentSelection = readSelection(),
  dirs: SyncDirs = DEFAULT_DIRS,
): void {
  if (!fs.existsSync(dirs.acpAgentsDir)) {
    throw new Error(`agents catalog not found: ${dirs.acpAgentsDir}`)
  }
  // Phase 1 — load and validate everything in memory. No writes yet.
  const staged: Array<{ fileName: string; content: string }> = []
  for (const [role, fixedName] of Object.entries(ROLE_TO_FIXED)) {
    const fileName = sel[role as keyof AgentSelection] || SELECTION_DEFAULTS[role as keyof AgentSelection]
    if (!fileName || !isSafeFileName(fileName as string)) {
      throw new Error(`invalid agent selection for role '${role}': ${JSON.stringify(fileName)}`)
    }
    const srcFile = path.join(dirs.acpAgentsDir, fileName as string) // nosemgrep: path-join-resolve-traversal
    if (!fs.existsSync(srcFile)) {
      throw new Error(`selected agent definition missing from catalog: ${fileName} (role '${role}')`)
    }
    let agent: Record<string, unknown>
    try {
      agent = JSON.parse(fs.readFileSync(srcFile, "utf-8"))
    } catch (e) {
      throw new Error(`malformed agent definition in catalog: ${fileName} — ${e}`)
    }
    if (sel.model) {
      agent.model = sel.model
    } else {
      delete agent.model
    }
    staged.push({ fileName: fixedName, content: JSON.stringify(agent, null, 2) + "\n" })
  }
  // Phase 2 — transactional replacement with backup: stage a sibling temp
  // dir, move the old output aside, swap the new one in, and restore the
  // backup if the swap fails. No failure path loses the old generation.
  const tmpDir = dirs.agentsDir + `.tmp-${process.pid}`
  const backupDir = dirs.agentsDir + `.bak-${process.pid}`
  fs.rmSync(tmpDir, { recursive: true, force: true })
  fs.rmSync(backupDir, { recursive: true, force: true })
  fs.mkdirSync(tmpDir, { recursive: true })
  try {
    for (const { fileName, content } of staged) {
      // fileName comes from the ROLE_TO_FIXED constant, not user input
      fs.writeFileSync(path.join(tmpDir, fileName), content) // nosemgrep: path-join-resolve-traversal
    }
    fs.writeFileSync(path.join(tmpDir, "README.md"), README_MARKER) // nosemgrep: path-join-resolve-traversal
    const hadPrevious = fs.existsSync(dirs.agentsDir)
    if (hadPrevious) fs.renameSync(dirs.agentsDir, backupDir)
    try {
      fs.renameSync(tmpDir, dirs.agentsDir)
    } catch (e) {
      if (hadPrevious) fs.renameSync(backupDir, dirs.agentsDir) // restore
      throw e
    }
    fs.rmSync(backupDir, { recursive: true, force: true })
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
}
