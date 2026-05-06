// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Templates API — lists templates with metadata from bundled + user-local directories. */
import fs from "fs"
import path from "path"
import { execSync } from "child_process"
import { getUserConfigDir, getState } from "@/lib/local/sdpmPaths"

/** Bundled templates directory. */
const BUNDLED_TEMPLATES_DIR = path.resolve(process.cwd(), "..", "skill", "templates")

/** User-local templates directory. */
function getUserTemplatesDir(): string {
  return path.join(getUserConfigDir(), "templates")
}

export async function GET() {
  const userDir = getUserTemplatesDir()
  const bundledDir = BUNDLED_TEMPLATES_DIR
  const metadata: Record<string, Record<string, unknown>> = (getState().template_metadata as Record<string, Record<string, unknown>>) || {}

  const seen = new Set<string>()
  const templates: Array<Record<string, unknown>> = []

  // User templates first (shadow bundled)
  if (fs.existsSync(userDir)) {
    for (const f of fs.readdirSync(userDir).filter(f => f.endsWith(".pptx")).sort()) {
      const name = f.replace(/\.pptx$/, "")
      seen.add(name)
      let meta = metadata[name] || {}
      // If no stored metadata, analyze on-the-fly
      if (!meta.theme_colors) {
        try {
          const templatePath = path.join(userDir, f)
          const skillDir = path.resolve(process.cwd(), "..", "skill")
          const result = execSync(
            `python3 -c "import sys; sys.path.insert(0, '${skillDir}'); import json; from sdpm.analyzer import analyze_template; r=analyze_template(__import__('pathlib').Path('${templatePath}')); print(json.dumps({'theme_colors':r.get('theme_colors',{}),'fonts':r.get('fonts',{}),'layout_count':len(r.get('layouts',[]))}))"`,
            { encoding: "utf-8", timeout: 10000 }
          )
          meta = { ...meta, ...JSON.parse(result.trim()) }
        } catch { /* fallback */ }
      }
      templates.push({ name, source: "user", description: "", ...meta })
    }
  }

  // Bundled templates
  if (fs.existsSync(bundledDir)) {
    for (const f of fs.readdirSync(bundledDir).filter(f => f.endsWith(".pptx")).sort()) {
      const name = f.replace(/\.pptx$/, "")
      if (seen.has(name)) continue
      // Analyze builtin on-the-fly (lightweight)
      let meta: Record<string, unknown> = {}
      try {
        const templatePath = path.join(bundledDir, f)
        const skillDir = path.resolve(process.cwd(), "..", "skill")
        const result = execSync(
          `python3 -c "import sys; sys.path.insert(0, '${skillDir}'); import json; from sdpm.analyzer import analyze_template; r=analyze_template(__import__('pathlib').Path('${templatePath}')); print(json.dumps({'theme_colors':r.get('theme_colors',{}),'fonts':r.get('fonts',{}),'layout_count':len(r.get('layouts',[]))}))"`,
          { encoding: "utf-8", timeout: 10000 }
        )
        meta = JSON.parse(result.trim())
      } catch { /* fallback: no metadata */ }
      templates.push({ name, source: "builtin", description: "", ...meta })
    }
  }

  return Response.json({ templates })
}
