// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local PPTX download — serves a deck's output.pptx as an attachment named after the
 * deck title (`<name>.pptx`), the Local counterpart of the cloud `GET /decks/{id}/pptx`.
 * 404 when the deck has no output.pptx or is an HTML deck.
 * Local mode only.
 */

import fs from "fs"
import { resolveDeckDir } from "@/lib/local/deck-paths"
import { resolveWithin } from "@/lib/local/contained"
import { attachmentDisposition } from "@/lib/local/downloadName"

const PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

function readDeckJson(dp: string): Record<string, unknown> {
  for (const fname of ["deck.json", "presentation.json"]) {
    const p = resolveWithin(dp, fname)
    if (!p || !fs.existsSync(p)) continue
    try {
      const data = JSON.parse(fs.readFileSync(p, "utf-8"))
      return data && typeof data === "object" ? data : {}
    } catch {
      return {}
    }
  }
  return {}
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: deckId } = await params
  const dp = resolveDeckDir(deckId)
  if (!dp) return new Response("Not found", { status: 404 })
  const pptxPath = resolveWithin(dp, "output.pptx")
  const deckJson = readDeckJson(dp)
  if (deckJson.outputFormat === "html" || !pptxPath || !fs.existsSync(pptxPath)) return new Response("Not found", { status: 404 })

  return new Response(fs.readFileSync(pptxPath), {
    headers: {
      "Content-Type": PPTX_TYPE,
      "Content-Disposition": attachmentDisposition(deckJson.name || deckId, ".pptx"),
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "no-cache",
    },
  })
}
