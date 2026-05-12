// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Template Upload API — save .pptx + analyze metadata. */
import fs from "fs"
import path from "path"
import { execFileSync } from "child_process"
import { getUserConfigDir, getState, updateState } from "@/lib/local/sdpmPaths"

function getUserTemplatesDir(): string {
  return path.join(getUserConfigDir(), "templates")
}

export async function POST(req: Request) {
  const formData = await req.formData()
  const file = formData.get("file") as File | null
  const description = (formData.get("description") as string) || ""

  if (!file || !file.name.endsWith(".pptx")) {
    return Response.json({ error: ".pptx file required" }, { status: 400 })
  }

  const name = file.name.replace(/\.pptx$/, "")
  if (!/^[a-zA-Z0-9_\-\s.()]+$/.test(name)) {
    return Response.json({ error: "Invalid template name" }, { status: 400 })
  }

  const dir = getUserTemplatesDir()
  fs.mkdirSync(dir, { recursive: true })

  const realDir = fs.realpathSync(dir)
  const outputPath = path.resolve(realDir, `${name}.pptx`)
  if (!outputPath.startsWith(realDir + path.sep)) {
    return Response.json({ error: "Invalid template name" }, { status: 400 })
  }

  // Duplicate check
  if (fs.existsSync(outputPath)) {
    return Response.json({ error: `Template "${name}" already exists` }, { status: 409 })
  }

  // Write file
  const buffer = Buffer.from(await file.arrayBuffer())
  fs.writeFileSync(outputPath, buffer)

  // Analyze template
  let meta: Record<string, unknown> = { description }
  try {
    const skillDir = path.resolve(process.cwd(), "..", "skill")
    const script = `import sys; sys.path.insert(0, sys.argv[1]); import json; from sdpm.api import analyze_and_store_template; from pathlib import Path; r=analyze_and_store_template(Path(sys.argv[2]), description=sys.argv[3]); print(json.dumps(r, ensure_ascii=False))`
    const result = execFileSync("python3", ["-c", script, skillDir, outputPath, description], {
      encoding: "utf-8",
      timeout: 15000,
    })
    meta = JSON.parse(result.trim())
  } catch { /* fallback: minimal metadata */ }

  // Persist metadata to state.json
  const state = getState()
  const templateMetadata = (state.template_metadata as Record<string, unknown>) || {}
  templateMetadata[name] = meta
  updateState("template_metadata", templateMetadata)

  return Response.json({ uploaded: name, metadata: meta })
}
