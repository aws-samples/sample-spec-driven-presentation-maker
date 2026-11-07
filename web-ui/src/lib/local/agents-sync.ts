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
 * written alongside the files says so. The marker is `README.txt`: V3 reads
 * every `.md` and `.json` in the directory as an agent.
 *
 * The catalog is written in kiro-cli V2's form. Each generated definition is
 * read by both engines (`withPermissions`): V2 reads its `tools` /
 * `allowedTools` / `toolsSettings`, V3 its `tools` (with `subagent/<name>`
 * for each delegation target) and `permissions.rules`, derived from what V2
 * allows without asking. A catalog entry that already has `permissions` was
 * written for V3 and is used as it is.
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
  orchestrator: string
  composer: string
  style: string
  translate: string
  model?: string
}

export const SELECTION_DEFAULTS: AgentSelection = {
  orchestrator: "sdpm-orchestrator.json",
  composer: "sdpm-composer.json",
  style: "sdpm-style.json",
  translate: "sdpm-translate.json",
}

/** Role → the fixed file name the ACP layer spawns (invoke route contract). */
const ROLE_TO_FIXED: Record<string, string> = {
  orchestrator: "sdpm-orchestrator.json",
  composer: "sdpm-composer.json",
  style: "sdpm-style.json",
  translate: "sdpm-translate.json",
}

const README_FILE = "README.txt"

const README_MARKER = `# Generated directory — do not hand-edit

Files here are re-derived from \`../acp-agents/\` (the catalog) combined with
\`.sdpm/acp-agent-selection.json\` (your Settings selection + model) on every
agent spawn and on Settings save. Any manual change is overwritten.

To change agent behavior, edit \`sdpm/references/workflows/*.md\`; to change wiring, edit the
catalog in \`../acp-agents/\`; to switch agents or model, use Settings.
`

/** Validate that a filename is a simple .json file (no path traversal). */
export function isSafeFileName(name: string): boolean {
  return /^[\w-]+\.json$/.test(name)
}

const SELECTION_KEYS = ["orchestrator", "composer", "style", "translate", "model"] as const

/** The selection's own keys; older keys (`spec`, `vibe`, `single`, ...) are dropped. */
function pickSelection(raw: Record<string, unknown>): Partial<AgentSelection> {
  const picked: Partial<AgentSelection> = {}
  for (const key of SELECTION_KEYS) {
    if (raw[key] !== undefined) (picked as Record<string, unknown>)[key] = raw[key]
  }
  return picked
}

export function readSelection(dirs: SyncDirs = DEFAULT_DIRS): AgentSelection {
  try {
    if (fs.existsSync(dirs.configPath)) {
      const raw: unknown = JSON.parse(fs.readFileSync(dirs.configPath, "utf-8"))
      if (raw && typeof raw === "object" && !Array.isArray(raw)) return { ...SELECTION_DEFAULTS, ...pickSelection(raw as Record<string, unknown>) }
    }
  } catch {}
  return { ...SELECTION_DEFAULTS }
}

export function writeSelection(sel: AgentSelection, dirs: SyncDirs = DEFAULT_DIRS): void {
  fs.mkdirSync(path.dirname(dirs.configPath), { recursive: true })
  fs.writeFileSync(dirs.configPath, JSON.stringify(pickSelection(sel as unknown as Record<string, unknown>), null, 2) + "\n", "utf-8")
}

/** V2 tool names V3 reads as its `fs_read` capability (kiro-cli's own mapping). */
const FS_READ_TOOLS = new Set(["read", "glob", "grep"])
/** V2 tool names that are V3 capabilities of the same name. */
const SAME_NAME_CAPABILITIES = new Set(["web_fetch", "web_search"])
/** V2's delegation tool; V3 delegates through `subagent/<name>` tools, allowed by the subagent rule. */
const V2_DELEGATION_TOOL = "use_subagent"

const unknownToolsWarned = new Set<string>()

function stringList(field: string, value: unknown, fileName: string): string[] {
  if (value === undefined) return []
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) return [...value]
  console.warn("[agents-sync] %s: %s is not a list of names; not converted", fileName, field)
  return []
}

/**
 * The definition in the form both engines read: the V2 fields as they are, `subagent/<name>`
 * added to `tools` for each `toolsSettings.subagent.availableAgents`, and `permissions.rules`
 * allowing what `allowedTools` allows (`@<server>/<tool>` → one `mcp` rule; read / glob / grep →
 * `fs_read`; web_fetch / web_search → their own capability; `trustedAgents` → `subagent`). Any
 * other allowed tool gets no rule (V3 then asks, and the transport answers allow_once) and one
 * warning. A definition with `permissions` is returned unchanged.
 */
export function withPermissions(agent: Record<string, unknown>, fileName: string): Record<string, unknown> {
  if (agent.permissions !== undefined) return agent
  const subagent = ((agent.toolsSettings as { subagent?: Record<string, unknown> } | undefined)?.subagent) ?? {}
  const available = stringList("toolsSettings.subagent.availableAgents", subagent.availableAgents, fileName)
  const trusted = stringList("toolsSettings.subagent.trustedAgents", subagent.trustedAgents, fileName)
  const allowed = stringList("allowedTools", agent.allowedTools, fileName)

  const converted: Record<string, unknown> = { ...agent }
  const toolsListed = agent.tools === undefined || (Array.isArray(agent.tools) && agent.tools.every((t) => typeof t === "string"))
  const tools = stringList("tools", agent.tools, fileName)
  if (toolsListed) {
    for (const name of available) if (!tools.includes(`subagent/${name}`)) tools.push(`subagent/${name}`)
    if (agent.tools !== undefined || tools.length) converted.tools = tools
  }

  const mcp: string[] = []
  const capabilities: string[] = []
  for (const tool of allowed) {
    if (tool.startsWith("@") && tool.includes("/")) {
      if (!mcp.includes(tool.slice(1))) mcp.push(tool.slice(1))
    } else if (FS_READ_TOOLS.has(tool)) {
      if (!capabilities.includes("fs_read")) capabilities.push("fs_read")
    } else if (SAME_NAME_CAPABILITIES.has(tool)) {
      if (!capabilities.includes(tool)) capabilities.push(tool)
    } else if (tool !== V2_DELEGATION_TOOL && !unknownToolsWarned.has(`${fileName} ${tool}`)) {
      unknownToolsWarned.add(`${fileName} ${tool}`)
      console.warn("[agents-sync] %s: allowed tool %s has no V3 permission rule; V3 asks for it", fileName, tool)
    }
  }
  const rules: Record<string, unknown>[] = []
  if (mcp.length) rules.push({ capability: "mcp", match: mcp, effect: "allow" })
  for (const capability of capabilities) rules.push({ capability, effect: "allow" })
  if (trusted.length) rules.push({ capability: "subagent", match: trusted, effect: "allow" })
  converted.permissions = { rules }
  return converted
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
 *
 * The Settings model goes into every definition, except the composer's when
 * `opts.pinSubagentModel` is false: an engine whose sub-agents follow the
 * session's model (V3) then runs the composer on the chat's model and effort.
 */
export function syncToAgentsDir(
  sel: AgentSelection = readSelection(),
  dirs: SyncDirs = DEFAULT_DIRS,
  opts: { pinSubagentModel?: boolean } = {},
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
    if (sel.model && !(role === "composer" && opts.pinSubagentModel === false)) {
      agent.model = sel.model
    } else {
      delete agent.model
    }
    staged.push({ fileName: fixedName, content: JSON.stringify(withPermissions(agent, fileName as string), null, 2) + "\n" })
  }
  staged.push({ fileName: README_FILE, content: README_MARKER })
  // Both engines must read every definition (V3 only one with permissions), and V3 would read a
  // .md here as an agent.
  for (const { fileName, content } of staged) {
    if (fileName.endsWith(".md")) throw new Error(`generated agents directory would hold ${fileName}, which V3 reads as an agent`)
    if (!fileName.endsWith(".json")) continue
    const permissions = (JSON.parse(content) as { permissions?: unknown }).permissions
    if (typeof permissions !== "object" || permissions === null) throw new Error(`generated agent definition ${fileName} has no permissions`)
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
      // fileName comes from the ROLE_TO_FIXED constant or README_FILE, not user input
      fs.writeFileSync(path.join(tmpDir, fileName), content) // nosemgrep: path-join-resolve-traversal
    }
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
