// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Builtin Template Note API — per-user notes stored in state.json.
 *
 * Mirrors the cloud `PATCH /templates/builtin/<name>` endpoint. Notes live
 * under `template_metadata["builtin:<name>"].description` — the same key the
 * templates listing already uses for builtin analysis caches — so servers/local
 * and the L1 CLI pick them up through the engine without extra plumbing.
 */
import fs from "fs"
import path from "path"
import { getState, updateState, BUNDLED_TEMPLATES_DIR } from "@/lib/local/sdpmPaths"

export async function PATCH(req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  const body = await req.json() as { description?: string }

  if (typeof body.description !== "string") {
    return Response.json({ error: "Description must be a string" }, { status: 400 })
  }
  if (!/^[a-zA-Z0-9_\-\s.()]+$/.test(name)) {
    return Response.json({ error: "Invalid template name" }, { status: 400 })
  }

  // Notes can only target builtin templates that exist in the bundled directory.
  const realDir = fs.existsSync(BUNDLED_TEMPLATES_DIR) ? fs.realpathSync(BUNDLED_TEMPLATES_DIR) : BUNDLED_TEMPLATES_DIR
  // nosemgrep: path-join-resolve-traversal — containment check follows
  const filePath = path.resolve(realDir, `${name}.pptx`)
  if (!filePath.startsWith(realDir + path.sep)) {
    return Response.json({ error: "Invalid template name" }, { status: 400 })
  }
  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "Template not found" }, { status: 404 })
  }

  const state = getState()
  const templateMetadata = (state.template_metadata as Record<string, Record<string, unknown>>) || {}
  const key = `builtin:${name}`
  const description = body.description.trim()

  if (description) {
    templateMetadata[key] = { ...templateMetadata[key], description }
  } else if (templateMetadata[key]) {
    // Clear the note but keep the analysis cache (theme_colors etc.) intact.
    delete templateMetadata[key].description
  }
  updateState("template_metadata", templateMetadata)

  return Response.json({ updated: name, description })
}
