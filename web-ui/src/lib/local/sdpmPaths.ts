// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Shared helpers for local sdpm config/state paths. */
import fs from "fs"
import path from "path"
import os from "os"

/** Skill distribution root (repo's sdpm/ — engine package + references + templates). */
export const SDPM_ROOT = path.resolve(process.cwd(), "..", "sdpm")

/** Bundled templates directory (sdpm/templates/). */
export const BUNDLED_TEMPLATES_DIR = path.join(SDPM_ROOT, "templates")

/** Bundled styles directory (sdpm/references/examples/styles/). */
export const BUNDLED_STYLES_DIR = path.join(SDPM_ROOT, "references", "examples", "styles")

/** User config directory (~/.config/sdpm on macOS/Linux, %APPDATA%/sdpm on Windows). */
export function getUserConfigDir(): string {
  const base = process.platform === "win32"
    ? process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming")
    : process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config")
  return path.join(base, "sdpm")
}

/** User-local styles directory. */
export function getUserStylesDir(): string {
  return path.join(getUserConfigDir(), "styles")
}

/**
 * `output_dir` from the user's config.json with `~` expanded (sdpm.config.get_output_dir),
 * or null when the file, the key or valid JSON is missing.
 */
export function getConfiguredOutputDir(): string | null {
  try {
    const config = JSON.parse(fs.readFileSync(path.join(getUserConfigDir(), "config.json"), "utf-8"))
    const dir: unknown = config?.output_dir
    if (typeof dir !== "string" || !dir) return null
    if (dir === "~") return os.homedir()
    return /^~[/\\]/.test(dir) ? path.join(os.homedir(), dir.slice(2)) : dir
  } catch {
    return null
  }
}

/** State file path (~/.config/sdpm/state.json). */
export function getStateJsonPath(): string {
  return path.join(getUserConfigDir(), "state.json")
}

/** Read app state. Returns empty object if file missing. */
export function getState(): Record<string, unknown> {
  const p = getStateJsonPath()
  if (!fs.existsSync(p)) return {}
  return JSON.parse(fs.readFileSync(p, "utf-8"))
}

/** Update a single key in state.json (read-modify-write). */
export function updateState(key: string, value: unknown): void {
  const dir = getUserConfigDir()
  fs.mkdirSync(dir, { recursive: true })
  const p = getStateJsonPath()
  const state = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf-8")) : {}
  state[key] = value
  writeState(p, state)
}

/**
 * Write state.json atomically (temp file in the same directory, then rename): the local
 * MCP server and this Web UI share the file, so a reader must never see it half written.
 * Mirrors sdpm.config._write_state.
 */
function writeState(p: string, state: Record<string, unknown>): void {
  const tmp = path.join(path.dirname(p), `.state.${process.pid}.${Date.now()}.tmp`)
  try {
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2))
    fs.renameSync(tmp, p)
  } catch (e) {
    fs.rmSync(tmp, { force: true })
    throw e
  }
}

/**
 * Per-user notes on builtin templates (`state.json` → `builtin_template_notes`),
 * kept apart from the regenerable analysis cache — the local counterpart of the
 * cloud's `BUILTIN_NOTE#<name>` items. Notes still in the legacy location
 * (`template_metadata["builtin:<name>"].description`, ≤ 0.17) are moved here
 * on first read; sdpm.config.get_builtin_template_notes does the same in Python.
 * A legacy note wins over one already in the new section (only a ≤ 0.17 install writes
 * the legacy location after the move, so it is the newer edit). The rewrite is best
 * effort: a read-only config dir still gets its notes.
 */
export function getBuiltinTemplateNotes(): Record<string, string> {
  const state = getState()
  const notes = { ...((state.builtin_template_notes as Record<string, string>) || {}) }
  const metadata = (state.template_metadata as Record<string, Record<string, unknown>>) || {}
  let migrated = false
  for (const [key, entry] of Object.entries(metadata)) {
    if (!key.startsWith("builtin:") || !entry || typeof entry !== "object" || !("description" in entry)) continue
    const note = entry.description
    delete entry.description
    const name = key.slice("builtin:".length)
    if (typeof note === "string" && note.trim()) notes[name] = note.trim()
    migrated = true
  }
  if (migrated) {
    state.builtin_template_notes = notes
    state.template_metadata = metadata
    try {
      writeState(getStateJsonPath(), state)
    } catch {
      // Read-only config dir: return the notes without the rewrite.
    }
  }
  return notes
}

/** Set (non-empty) or clear (empty) the user's note on a builtin template. */
export function setBuiltinTemplateNote(name: string, description: string): void {
  const notes = getBuiltinTemplateNotes()
  if (description) notes[name] = description
  else delete notes[name]
  updateState("builtin_template_notes", notes)
}

/** List style HTML files from a directory. Returns [{name, description, html}]. */
export function listStylesFromDir(dir: string): Array<{ name: string; description: string; html: string }> {
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir)
    .filter(f => f.endsWith(".html") && !f.startsWith("."))
    .sort()
    .map(f => {
      const name = f.replace(/\.html$/, "")
      // `dir` is a server-side constant (bundled/user styles dir) and `f` comes
      // from readdirSync filtered to *.html — no user input reaches this join.
      // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      const html = fs.readFileSync(path.join(dir, f), "utf-8")
      const titleMatch = html.match(/<title>(.*?)<\/title>/i)
      const description = titleMatch ? titleMatch[1].trim() : ""
      return { name, description, html }
    })
}
