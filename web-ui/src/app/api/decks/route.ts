// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Deck List API — scans ~/Documents/SDPM-Presentations/ for decks.
 * Local mode only.
 */



import fs from "fs"
import path from "path"
import { DECK_ROOT } from "@/lib/local/deck-paths"

export async function GET() {
  if (!fs.existsSync(DECK_ROOT)) {
    fs.mkdirSync(DECK_ROOT, { recursive: true })
    return Response.json({ decks: [], favoriteIds: [] })
  }

  // Read favorites index
  let favoriteIds: string[] = []
  const indexPath = path.join(DECK_ROOT, "decks.json")
  try {
    const idx = JSON.parse(fs.readFileSync(indexPath, "utf-8"))
    favoriteIds = idx.favoriteIds || []
  } catch {}

  const entries = fs.readdirSync(DECK_ROOT, { withFileTypes: true })
  const decks = entries
    .filter(e => e.isDirectory())
    .map(e => {
      const deckId = e.name
      const dp = path.join(DECK_ROOT, deckId)
      let name = deckId
      for (const fname of ["deck.json", "presentation.json"]) {
        const p = path.join(dp, fname)
        if (fs.existsSync(p)) {
          try { name = JSON.parse(fs.readFileSync(p, "utf-8")).name || deckId } catch {}
          break
        }
      }
      let slideCount = 0
      const slidesDir = path.join(dp, "slides")
      if (fs.existsSync(slidesDir)) {
        slideCount = fs.readdirSync(slidesDir).filter(f => f.endsWith(".json")).length
      }
      return { deckId, name, slideCount, updatedAt: new Date().toISOString(), thumbnailUrl: null }
    })
    .sort((a, b) => b.deckId.localeCompare(a.deckId))

  return Response.json({ decks, favoriteIds })
}
