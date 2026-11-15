// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Template Download API — serves .pptx file by name. */
import fs from "fs"
import path from "path"
import { getUserConfigDir, BUNDLED_TEMPLATES_DIR } from "@/lib/local/sdpmPaths"
import { resolveWithin } from "@/lib/local/contained"

function findTemplate(name: string): string | null {
  const filename = name.endsWith(".pptx") ? name : `${name}.pptx`
  // Validate filename contains no path separators
  if (path.basename(filename) !== filename) return null

  const userDir = path.join(getUserConfigDir(), "templates")
  const userPath = resolveWithin(userDir, filename)
  if (userPath && fs.existsSync(userPath)) return userPath
  const bundledPath = resolveWithin(BUNDLED_TEMPLATES_DIR, filename)
  if (bundledPath && fs.existsSync(bundledPath)) return bundledPath
  return null
}

export async function GET(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  const filePath = findTemplate(name)
  if (!filePath) {
    return Response.json({ error: "Template not found" }, { status: 404 })
  }
  const data = fs.readFileSync(filePath)
  return new Response(data, {
    headers: {
      "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "Content-Disposition": `attachment; filename="${path.basename(filePath)}"`,
    },
  })
}
