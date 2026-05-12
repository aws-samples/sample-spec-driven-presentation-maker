// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Template Delete API. */
import fs from "fs"
import path from "path"
import { getUserConfigDir, getState, updateState } from "@/lib/local/sdpmPaths"

export async function PATCH(req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  const body = await req.json() as { description?: string; newName?: string }

  const state = getState()
  const templateMetadata = (state.template_metadata as Record<string, Record<string, unknown>>) || {}

  // Rename
  if (body.newName) {
    const newName = body.newName.trim()
    if (!/^[a-zA-Z0-9_\-]+$/.test(newName)) {
      return Response.json({ error: "Letters, numbers, hyphens, underscores only" }, { status: 400 })
    }
    const dir = path.join(getUserConfigDir(), "templates")
    if (!fs.existsSync(dir)) {
      return Response.json({ error: "Template not found" }, { status: 404 })
    }
    const realDir = fs.realpathSync(dir)
    // nosemgrep: path-join-resolve-traversal — containment check follows
    const oldPath = path.join(realDir, `${name}.pptx`)
    // nosemgrep: path-join-resolve-traversal — containment check follows
    const newPath = path.join(realDir, `${newName}.pptx`)
    if (!oldPath.startsWith(realDir + path.sep) || !newPath.startsWith(realDir + path.sep)) {
      return Response.json({ error: "Invalid template name" }, { status: 400 })
    }
    if (!fs.existsSync(oldPath)) {
      return Response.json({ error: "Template not found" }, { status: 404 })
    }
    if (fs.existsSync(newPath)) {
      return Response.json({ error: "Name already exists" }, { status: 409 })
    }
    fs.renameSync(oldPath, newPath)
    // Move metadata
    if (templateMetadata[name]) {
      templateMetadata[newName] = { ...templateMetadata[name], name: newName }
      delete templateMetadata[name]
      updateState("template_metadata", templateMetadata)
    }
    return Response.json({ renamed: { from: name, to: newName } })
  }

  // Update description
  if (body.description !== undefined) {
    if (!templateMetadata[name]) {
      templateMetadata[name] = {}
    }
    templateMetadata[name].description = body.description
    updateState("template_metadata", templateMetadata)
    return Response.json({ updated: name, description: body.description })
  }

  return Response.json({ error: "No action specified" }, { status: 400 })
}

export async function DELETE(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  if (!/^[a-zA-Z0-9_\-\s.()]+$/.test(name)) {
    return Response.json({ error: "Invalid template name" }, { status: 400 })
  }

  const dir = path.join(getUserConfigDir(), "templates")
  const realDir = fs.existsSync(dir) ? fs.realpathSync(dir) : dir
  const filePath = path.resolve(realDir, `${name}.pptx`)
  if (!filePath.startsWith(realDir + path.sep) && filePath !== path.join(realDir, `${name}.pptx`)) {
    return Response.json({ error: "Invalid template name" }, { status: 400 })
  }

  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "Template not found" }, { status: 404 })
  }

  fs.unlinkSync(filePath)

  // Remove metadata from state.json
  const state = getState()
  const templateMetadata = (state.template_metadata as Record<string, unknown>) || {}
  delete templateMetadata[name]
  updateState("template_metadata", templateMetadata)

  return Response.json({ deleted: name })
}
