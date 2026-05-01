// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Style Detail API — returns full HTML for a single style. */
import fs from "fs"
import path from "path"

const STYLES_DIR = path.resolve(process.cwd(), "..", "skill", "references", "examples", "styles")

export async function GET(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  const filePath = path.join(STYLES_DIR, `${name}.html`)
  if (!fs.existsSync(filePath)) return Response.json({ fullHtml: "" }, { status: 404 })
  const fullHtml = fs.readFileSync(filePath, "utf-8")
  return Response.json({ fullHtml })
}
