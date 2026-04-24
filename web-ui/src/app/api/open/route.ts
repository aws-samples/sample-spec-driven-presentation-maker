// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Open API — opens a deck file or directory with the OS default handler.
 * macOS: `open`, Linux: `xdg-open`, Windows: `start`
 */
import { exec } from "child_process"
import path from "path"
import fs from "fs"
import { DECK_ROOT } from "@/lib/local/deck-paths"

export async function POST(req: Request) {
  const { deckId, file } = await req.json()
  if (!deckId) return Response.json({ error: "deckId required" }, { status: 400 })

  const deckDir = path.join(DECK_ROOT, deckId)
  if (!fs.existsSync(deckDir)) return Response.json({ error: "deck not found" }, { status: 404 })

  const target = file ? path.join(deckDir, file) : deckDir
  if (!target.startsWith(deckDir)) return Response.json({ error: "invalid path" }, { status: 400 })
  if (!fs.existsSync(target)) return Response.json({ error: "file not found" }, { status: 404 })

  const cmd = process.platform === "win32" ? "start" : process.platform === "linux" ? "xdg-open" : "open"
  exec(`${cmd} "${target}"`)

  return Response.json({ ok: true })
}
