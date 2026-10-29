// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Preview File Server — serves deck assets (PNG, JSON, PPTX) from filesystem.
 * URL: /api/preview/{deckId}/{subpath...}
 * Local mode only.
 *
 * HTML is served for exactly two paths of an HTML deck, each with a CSP
 * `sandbox` header so the document never runs with this app's origin:
 *   - `output.html`: the reveal.js deck (`sandbox allow-scripts allow-popups`)
 *   - `preview/<slug>.html`: static slide thumbnails (`sandbox`, no scripts)
 * Every other `.html` path is 404.
 */



import fs from "fs"
import path from "path"
import { resolveDeckPath } from "@/lib/local/deck-paths"

const MIME: Record<string, string> = {
  ".png": "image/png",
  ".json": "application/json",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".svg": "image/svg+xml",
}

const HTML_PREVIEW_FILE_RE = /^[a-z0-9][a-z0-9_-]*\.html$/

/** CSP sandbox for an allowed HTML path, or null when the path must not be served. */
function htmlSandbox(rest: string[]): string | null {
  if (rest.length === 1 && rest[0] === "output.html") return "sandbox allow-scripts allow-popups"
  if (rest.length === 2 && rest[0] === "preview" && HTML_PREVIEW_FILE_RE.test(rest[1])) return "sandbox"
  return null
}

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const segments = (await params).path
  if (!segments || segments.length < 2) return new Response("Not found", { status: 404 })

  const [deckId, ...rest] = segments
  const filePath = resolveDeckPath(deckId, ...rest)
  if (!filePath) return new Response("Forbidden", { status: 403 })
  if (!fs.existsSync(filePath)) return new Response("Not found", { status: 404 })

  const ext = path.extname(filePath).toLowerCase()
  if (ext === ".html") {
    const sandbox = htmlSandbox(rest)
    if (!sandbox) return new Response("Not found", { status: 404 })
    return new Response(fs.readFileSync(filePath), {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": sandbox,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache",
      },
    })
  }
  const contentType = MIME[ext]
  if (!contentType) return new Response("Not found", { status: 404 })
  const body = fs.readFileSync(filePath)

  return new Response(body, {
    headers: { "Content-Type": contentType, "Cache-Control": "no-cache" },
  })
}
