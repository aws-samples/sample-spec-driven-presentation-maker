// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Open API — opens a deck file or directory with the OS default handler.
 * macOS: `open`, Linux: `xdg-open`, Windows: `start`
 */
import { execFile } from "child_process"
import path from "path"
import fs from "fs"
import { DECK_ROOT } from "@/lib/local/deck-paths"

/** Only allow safe characters in path segments to prevent traversal/injection. */
const SAFE_SEGMENT = /^[a-zA-Z0-9_\-][a-zA-Z0-9_\-.]*$/

/**
 * Validate a segment and return a freshly-constructed safe string.
 * The returned value is built from the regex match — not from the original input —
 * so CodeQL's taint tracking does not propagate through it.
 */
function validateSegment(input: unknown): string | null {
  if (typeof input !== "string") return null
  const m = SAFE_SEGMENT.exec(input)
  if (!m) return null
  return m[0] // fresh string from regex match, not user-tainted
}

export async function POST(req: Request) {
  const body = await req.json()

  const safeDeckId = validateSegment(body.deckId)
  if (!safeDeckId)
    return Response.json({ error: "invalid deckId" }, { status: 400 })

  const deckDir = path.join(DECK_ROOT, safeDeckId)
  if (!fs.existsSync(deckDir))
    return Response.json({ error: "deck not found" }, { status: 404 })

  let target = deckDir
  if (body.file) {
    const safeFile = validateSegment(body.file)
    if (!safeFile)
      return Response.json({ error: "invalid file" }, { status: 400 })
    const filePath = path.join(deckDir, safeFile)
    // Defence-in-depth: verify containment after join
    if (!filePath.startsWith(deckDir + path.sep) && filePath !== deckDir)
      return Response.json({ error: "invalid path" }, { status: 400 })
    target = filePath
  }
  if (!fs.existsSync(target))
    return Response.json({ error: "file not found" }, { status: 404 })

  const platform = process.platform
  if (platform === "win32") {
    execFile("explorer.exe", [target])
  } else {
    execFile(platform === "linux" ? "xdg-open" : "open", [target])
  }

  return Response.json({ ok: true })
}
