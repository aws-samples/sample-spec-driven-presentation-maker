// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Style Delete API — delete a user style HTML file. */
import fs from "fs"
import path from "path"
import { getUserStylesDir } from "@/lib/local/sdpmPaths"

export async function DELETE(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    return Response.json({ error: "invalid style name" }, { status: 400 })
  }

  const filePath = path.join(getUserStylesDir(), `${name}.html`)
  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "style not found" }, { status: 404 })
  }

  fs.unlinkSync(filePath)
  return Response.json({ deleted: name })
}
