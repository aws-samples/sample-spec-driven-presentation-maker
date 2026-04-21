// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Styles API — lists available style HTML files from skill/references/examples/styles/. */
import fs from "fs"
import path from "path"

const STYLES_DIR = path.resolve(process.cwd(), "..", "skill", "references", "examples", "styles")

export async function GET() {
  if (!fs.existsSync(STYLES_DIR)) return Response.json({ styles: [] })
  const files = fs.readdirSync(STYLES_DIR).filter(f => f.endsWith(".html"))
  const styles = files.map(f => {
    const name = f.replace(/\.html$/, "")
    const html = fs.readFileSync(path.join(STYLES_DIR, f), "utf-8")
    // Extract first slide as cover preview (content before second <section> or full)
    const coverEnd = html.indexOf("<section", html.indexOf("<section") + 1)
    const coverHtml = coverEnd > 0 ? html.slice(0, coverEnd) + "</section>" : html
    return { name, coverHtml }
  })
  return Response.json({ styles })
}
