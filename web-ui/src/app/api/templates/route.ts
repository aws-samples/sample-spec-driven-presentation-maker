// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Templates API — lists templates with metadata from bundled + user-local directories. */
import fs from "fs"
import path from "path"
import { execFileSync } from "child_process"
import { getUserConfigDir, getState, updateState } from "@/lib/local/sdpmPaths"

/** Bundled templates directory. */
const BUNDLED_TEMPLATES_DIR = path.resolve(process.cwd(), "..", "skill", "templates")

/** mcp-local directory (uv-managed venv with sdpm deps). */
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "mcp-local")

/** User-local templates directory. */
function getUserTemplatesDir(): string {
  return path.join(getUserConfigDir(), "templates")
}

export async function GET() {
  const userDir = getUserTemplatesDir()
  const bundledDir = BUNDLED_TEMPLATES_DIR
  const state = getState()
  const metadata: Record<string, Record<string, unknown>> = (state.template_metadata as Record<string, Record<string, unknown>>) || {}
  let metadataUpdated = false

  const seen = new Set<string>()
  const templates: Array<Record<string, unknown>> = []

  const skillDir = path.resolve(process.cwd(), "..", "skill")

  function analyzeAndCache(templatePath: string, name: string): Record<string, unknown> {
    try {
      const script = `import sys; sys.path.insert(0, sys.argv[1]); import json; from sdpm.analyzer import analyze_template; r=analyze_template(__import__('pathlib').Path(sys.argv[2])); print(json.dumps({'theme_colors':r.get('theme_colors',{}),'fonts':r.get('fonts',{}),'layout_count':len(r.get('layouts',[]))}))`
      const result = execFileSync("uv", ["run", "--directory", MCP_LOCAL_DIR, "python", "-c", script, skillDir, templatePath], {
        encoding: "utf-8",
        timeout: 10000,
        cwd: MCP_LOCAL_DIR,
      })
      const parsed = JSON.parse(result.trim())
      metadata[name] = { ...metadata[name], ...parsed }
      metadataUpdated = true
      return parsed
    } catch { return {} }
  }

  // User templates first (shadow bundled)
  if (fs.existsSync(userDir)) {
    for (const f of fs.readdirSync(userDir).filter(f => f.endsWith(".pptx")).sort()) {
      const name = f.replace(/\.pptx$/, "")
      seen.add(name)
      let meta = metadata[name] || {}
      if (!meta.theme_colors) {
        meta = { ...meta, ...analyzeAndCache(path.join(userDir, f), name) }
      }
      templates.push({ name, source: "user", description: "", ...meta })
    }
  }

  // Bundled templates
  if (fs.existsSync(bundledDir)) {
    for (const f of fs.readdirSync(bundledDir).filter(f => f.endsWith(".pptx")).sort()) {
      const name = f.replace(/\.pptx$/, "")
      if (seen.has(name)) continue
      const cacheKey = `builtin:${name}`
      let meta = metadata[cacheKey] || {}
      if (!meta.theme_colors) {
        meta = analyzeAndCache(path.join(bundledDir, f), cacheKey)
      }
      templates.push({ name, source: "builtin", description: "", ...meta })
    }
  }

  // Persist cache if updated
  if (metadataUpdated) {
    updateState("template_metadata", metadata)
  }

  return Response.json({ templates })
}
