// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Style API — save a user style HTML file. */
import fs from "fs"
import path from "path"
import { getUserStylesDir } from "@/lib/local/sdpmPaths"

export async function POST(req: Request) {
  const { name, html } = await req.json() as { name: string; html: string }
  if (!name || !html) {
    return Response.json({ error: "name and html required" }, { status: 400 })
  }
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    return Response.json({ error: "invalid style name" }, { status: 400 })
  }

  const dir = getUserStylesDir()
  fs.mkdirSync(dir, { recursive: true })
  const rootDir = fs.realpathSync(dir)
  const outputPath = path.resolve(rootDir, `${name}.html`)
  if (!outputPath.startsWith(rootDir + path.sep)) {
    return Response.json({ error: "invalid style name" }, { status: 400 })
  }
  fs.writeFileSync(outputPath, html, "utf-8")
  return Response.json({ saved: name })
}
