// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local outline write API — writes `specs/outline.md` for a deck on the filesystem.
 * Local mode only. Mirrors the cloud Lambda `PUT /decks/{id}/specs/outline`.
 */

import fs from "fs"
import path from "path"
import { resolveDeckDir } from "@/lib/local/deck-paths"

const OUTLINE_MAX_BYTES = 256 * 1024

export async function PUT(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: deckId } = await params
  const dp = resolveDeckDir(deckId)
  if (!dp || !fs.existsSync(dp)) {
    return Response.json({ error: "Deck not found" }, { status: 404 })
  }

  let content: unknown
  try {
    content = ((await req.json()) as { content?: unknown })?.content
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 })
  }
  if (typeof content !== "string") return Response.json({ error: "content must be a string" }, { status: 400 })
  if (content.includes("\0")) return Response.json({ error: "content must not contain NUL bytes" }, { status: 400 })
  const bytes = Buffer.byteLength(content, "utf-8")
  if (bytes > OUTLINE_MAX_BYTES) {
    return Response.json({ error: `content exceeds ${OUTLINE_MAX_BYTES} bytes` }, { status: 400 })
  }

  const specsDir = path.join(dp, "specs")
  fs.mkdirSync(specsDir, { recursive: true })
  fs.writeFileSync(path.join(specsDir, "outline.md"), content, "utf-8")
  return Response.json({ bytes })
}
