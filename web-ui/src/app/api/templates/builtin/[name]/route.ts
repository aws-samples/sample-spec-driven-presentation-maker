// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Builtin Template Note API — per-user notes stored in state.json.
 *
 * Mirrors the cloud `PATCH /templates/builtin/<name>` endpoint. Notes live in
 * their own `builtin_template_notes` section (see getBuiltinTemplateNotes), which
 * servers/local and the L1 CLI read through sdpm.config.get_builtin_template_notes.
 */
import fs from "fs"
import path from "path"
import { setBuiltinTemplateNote, BUNDLED_TEMPLATES_DIR } from "@/lib/local/sdpmPaths"

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

  const description = body.description.trim()
  setBuiltinTemplateNote(name, description)

  return Response.json({ updated: name, description })
}
