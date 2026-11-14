// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Style API — save a user style HTML file. */
import fs from "fs"
import { getUserStylesDir } from "@/lib/local/sdpmPaths"
import { resolveWithin } from "@/lib/local/contained"
import { rejectCrossSite } from "@/lib/local/requestGuard"

export async function POST(req: Request) {
  const refused = rejectCrossSite(req)
  if (refused) return refused
  const { name, html } = await req.json() as { name: string; html: string }
  if (!name || !html) {
    return Response.json({ error: "name and html required" }, { status: 400 })
  }
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    return Response.json({ error: "invalid style name" }, { status: 400 })
  }

  const dir = getUserStylesDir()
  fs.mkdirSync(dir, { recursive: true })
  // Refuses a target that is a symlink leading out of the styles directory (or a dangling one).
  const outputPath = resolveWithin(dir, `${name}.html`)
  if (!outputPath) {
    return Response.json({ error: "invalid style name" }, { status: 400 })
  }
  fs.writeFileSync(outputPath, html, "utf-8")
  return Response.json({ saved: name })
}
