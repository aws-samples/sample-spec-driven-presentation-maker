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
  fs.writeFileSync(p, JSON.stringify(state, null, 2))
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
