// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Template Download API — serves .pptx file by name. */
import fs from "fs"
import path from "path"
import { getUserConfigDir } from "@/lib/local/sdpmPaths"

const BUNDLED_TEMPLATES_DIR = path.resolve(process.cwd(), "..", "skill", "templates")

function findTemplate(name: string): string | null {
  const filename = name.endsWith(".pptx") ? name : `${name}.pptx`
  const userPath = path.join(getUserConfigDir(), "templates", filename)
  if (fs.existsSync(userPath)) return userPath
  const bundledPath = path.join(BUNDLED_TEMPLATES_DIR, filename)
  if (fs.existsSync(bundledPath)) return bundledPath
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
