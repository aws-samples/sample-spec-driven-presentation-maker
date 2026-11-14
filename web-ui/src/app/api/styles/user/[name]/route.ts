// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Style API — delete or rename a user style HTML file. */
import fs from "fs"
import path from "path"
import { getUserStylesDir, getState, updateState } from "@/lib/local/sdpmPaths"

const NAME_RE = /^[a-zA-Z0-9_-]+$/

export async function DELETE(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  if (!NAME_RE.test(name)) {
    return Response.json({ error: "invalid style name" }, { status: 400 })
  }

  const filePath = path.join(getUserStylesDir(), `${name}.html`)
  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "style not found" }, { status: 404 })
  }

  fs.unlinkSync(filePath)
  return Response.json({ deleted: name })
}

export async function PATCH(req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  const { newName } = await req.json() as { newName: string }

  if (!NAME_RE.test(name) || !NAME_RE.test(newName)) {
    return Response.json({ error: "invalid style name (alphanumeric, hyphens, underscores only)" }, { status: 400 })
  }

  const dir = getUserStylesDir()
  const oldPath = path.join(dir, `${name}.html`)
  const newPath = path.join(dir, `${newName}.html`)

  if (!fs.existsSync(oldPath)) {
    return Response.json({ error: "style not found" }, { status: 404 })
  }
  if (fs.existsSync(newPath)) {
    return Response.json({ error: "a style with that name already exists" }, { status: 409 })
  }

  fs.renameSync(oldPath, newPath)

  // Update pin references in state.json
  try {
    const pinned = getState().pinned_styles
    if (Array.isArray(pinned) && pinned.includes(name)) {
      updateState("pinned_styles", pinned.map(s => (s === name ? newName : s)))
    }
  } catch { /* ignore corrupt state */ }

  return Response.json({ renamed: { from: name, to: newName } })
}
