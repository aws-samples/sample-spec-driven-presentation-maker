// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local User Guide API — save a guide of the user's own into the guide collection. */
import fs from "fs"
import { getUserGuidesDir } from "@/lib/local/sdpmPaths"
import { resolveWithin } from "@/lib/local/contained"
import { isGuideName } from "@/lib/local/guideName"
import { rejectCrossSite } from "@/lib/local/requestGuard"

export async function POST(req: Request) {
  const refused = rejectCrossSite(req)
  if (refused) return refused
  const { name, text } = await req.json() as { name: string; text: string }
  if (!text) {
    return Response.json({ error: "name and text required" }, { status: 400 })
  }
  // The frontmatter grammar is the engine's, so it is checked when the guide is read and
  // reported in the listing. The one mistake worth catching here is the common one: a file
  // with no frontmatter at all, which would be excluded from every hand-over.
  if (!text.startsWith("---")) {
    return Response.json({ error: "a guide starts with a --- frontmatter block" }, { status: 400 })
  }
  if (!isGuideName(name)) {
    return Response.json({ error: "invalid guide name" }, { status: 400 })
  }

  const dir = getUserGuidesDir()
  fs.mkdirSync(dir, { recursive: true })
  // Refuses a target that is a symlink leading out of the guides directory (or a dangling one).
  const outputPath = resolveWithin(dir, `${name}.md`)
  if (!outputPath) {
    return Response.json({ error: "invalid guide name" }, { status: 400 })
  }
  fs.writeFileSync(outputPath, text, "utf-8")
  return Response.json({ saved: name })
}
