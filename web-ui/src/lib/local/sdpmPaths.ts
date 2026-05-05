// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Shared helpers for local sdpm config/state paths. */
import fs from "fs"
import path from "path"
import os from "os"

/** Bundled styles directory (skill/references/examples/styles/). */
export const BUNDLED_STYLES_DIR = path.resolve(process.cwd(), "..", "skill", "references", "examples", "styles")

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

/** List style HTML files from a directory. Returns [{name, description, coverHtml}]. */
export function listStylesFromDir(dir: string): Array<{ name: string; description: string; coverHtml: string }> {
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir)
    .filter(f => f.endsWith(".html") && !f.startsWith("."))
    .sort()
    .map(f => {
      const name = f.replace(/\.html$/, "")
      const html = fs.readFileSync(path.join(dir, f), "utf-8")
      const titleMatch = html.match(/<title>(.*?)<\/title>/i)
      const description = titleMatch ? titleMatch[1].trim() : ""
      // Extract first slide as cover: find first <div class="slide..."> to second
      const slideRegex = /<div class="slide[\s"]/g
      const firstMatch = slideRegex.exec(html)
      if (!firstMatch) return { name, description, coverHtml: html }
      const first = firstMatch.index
      const secondMatch = slideRegex.exec(html)
      const slideHtml = secondMatch ? html.slice(first, secondMatch.index) : html.slice(first, html.indexOf("</body", first) || undefined)
      // Build standalone doc with head styles + body padding reset
      const headMatch = html.match(/<head[^>]*>([\s\S]*?)<\/head>/i)
      const head = headMatch ? headMatch[1] : ""
      const coverHtml = `<!DOCTYPE html><html><head>${head}<style>body{margin:0!important;padding:0!important;background:transparent!important;overflow:hidden!important;zoom:1!important}.slide{margin:0 auto!important}</style></head><body>${slideHtml}</body></html>`
      return { name, description, coverHtml }
    })
}
