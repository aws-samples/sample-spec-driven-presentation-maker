// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Display copies of style HTML for the Local routes: the engine draws the catalog icons a
 * style references (`sdpm.knowledge.assets.style_icons`). The Web UI holds no catalog
 * knowledge; on any failure the HTML is shown as stored.
 */
import crypto from "crypto"
import path from "path"
import { spawn } from "child_process"
import { SDPM_ROOT } from "@/lib/local/sdpmPaths"

/** servers/local directory (uv-managed venv with sdpm deps). */
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
const TIMEOUT_MS = 20_000
const CACHE_MAX = 64
const RETRY_AFTER_MS = 60_000
const SCRIPT = [
  "import sys, json",
  "sys.path.insert(0, sys.argv[1])",
  "from sdpm.knowledge.assets.style_icons import inline_style_icons_many",
  "json.dump(inline_style_icons_many(json.load(sys.stdin)), sys.stdout)",
].join("\n")

/** sha256(html) → display copy. Map keeps insertion order, so the first key is the oldest. */
const cache = new Map<string, string>()
let failedAt = 0

function key(html: string): string {
  return crypto.createHash("sha256").update(html).digest("hex")
}

function remember(k: string, html: string): void {
  cache.delete(k)
  cache.set(k, html)
  while (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value as string)
}

function runEngine(htmls: string[]): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const child = spawn("uv", ["run", "--directory", MCP_LOCAL_DIR, "python", "-c", SCRIPT, SDPM_ROOT], { cwd: MCP_LOCAL_DIR })
    let out = ""
    let err = ""
    const timer = setTimeout(() => { child.kill(); reject(new Error("timed out")) }, TIMEOUT_MS)
    child.stdout.setEncoding("utf-8")
    child.stderr.setEncoding("utf-8")
    child.stdout.on("data", (chunk: string) => { out += chunk })
    child.stderr.on("data", (chunk: string) => { err += chunk })
    child.on("error", (e) => { clearTimeout(timer); reject(e) })
    child.on("close", (code) => {
      clearTimeout(timer)
      if (code !== 0) return reject(new Error(`exit ${code}: ${err.slice(-500)}`))
      try {
        const parsed: unknown = JSON.parse(out)
        if (!Array.isArray(parsed) || parsed.length !== htmls.length || !parsed.every(h => typeof h === "string")) {
          return reject(new Error("unexpected output"))
        }
        resolve(parsed as string[])
      } catch (e) { reject(e) }
    })
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(htmls))
  })
}

/** Display copies of `htmls`, in order: each with the catalog icons it references drawn in. */
export async function inlineStyleIcons(htmls: string[]): Promise<string[]> {
  const keys = htmls.map(key)
  const todo = [...new Set(htmls.filter((h, i) => h.includes("<use") && !cache.has(keys[i])))]
  // The deck route is polled: after a failure, wait before spawning the engine again.
  if (todo.length > 0 && Date.now() - failedAt >= RETRY_AFTER_MS) {
    try {
      const shown = await runEngine(todo)
      todo.forEach((h, i) => remember(key(h), shown[i]))
    } catch (e) {
      failedAt = Date.now()
      console.warn("[styleIcons] icons not drawn:", e instanceof Error ? e.message : e)
    }
  }
  return htmls.map((h, i) => cache.get(keys[i]) ?? h)
}

/** Test hook: forget cached copies and the last failure. */
export function resetStyleIconsCache(): void {
  cache.clear()
  failedAt = 0
}
