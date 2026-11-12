// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Style Detail API — returns a single style (user-local first, then bundled):
 * `fullHtml` is the stored file (Export / Copy), `html` the display copy with the
 * referenced catalog icons drawn in.
 */
import fs from "fs"
import path from "path"
import { BUNDLED_STYLES_DIR, getUserStylesDir } from "@/lib/local/sdpmPaths"
import { inlineStyleIcons } from "@/lib/local/styleIcons"

export async function GET(_req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) return Response.json({ fullHtml: "" }, { status: 400 })

  // Search user-local first, then bundled
  for (const dir of [getUserStylesDir(), BUNDLED_STYLES_DIR]) {
    const filePath = path.join(dir, `${name}.html`)
    if (fs.existsSync(filePath)) {
      const fullHtml = fs.readFileSync(filePath, "utf-8")
      const [html] = await inlineStyleIcons([fullHtml])
      return Response.json({ fullHtml, html })
    }
  }
  return Response.json({ fullHtml: "" }, { status: 404 })
}
