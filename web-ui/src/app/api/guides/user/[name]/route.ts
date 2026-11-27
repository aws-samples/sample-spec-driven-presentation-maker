// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Guide API — delete or rename a guide of the user's own. */
import fs from "fs"
import path from "path"
import { getUserGuidesDir } from "@/lib/local/sdpmPaths"
import { isGuideName } from "@/lib/local/guideName"

export async function DELETE(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  if (!isGuideName(name)) {
    return Response.json({ error: "invalid guide name" }, { status: 400 })
  }

  const filePath = path.join(getUserGuidesDir(), `${name}.md`)
  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "guide not found" }, { status: 404 })
  }

  fs.unlinkSync(filePath)
  return Response.json({ deleted: name })
}

export async function PATCH(req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  const { newName } = await req.json() as { newName: string }

  if (!isGuideName(name) || !isGuideName(newName)) {
    return Response.json({ error: "invalid guide name (no dots or separators)" }, { status: 400 })
  }

  const dir = getUserGuidesDir()
  const oldPath = path.join(dir, `${name}.md`)
  const newPath = path.join(dir, `${newName}.md`)

  if (!fs.existsSync(oldPath)) {
    return Response.json({ error: "guide not found" }, { status: 404 })
  }
  if (fs.existsSync(newPath)) {
    return Response.json({ error: "a guide with that name already exists" }, { status: 409 })
  }

  // No pin bookkeeping: guides have no pins.
  fs.renameSync(oldPath, newPath)
  return Response.json({ renamed: { from: name, to: newName } })
}
