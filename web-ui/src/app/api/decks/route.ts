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
    .filter(e => e.isDirectory() && !e.name.startsWith("."))
    .map(e => {
      const deckId = e.name
      const dp = path.join(DECK_ROOT, deckId)
      let name = deckId
      let isHtml = false
      for (const fname of ["deck.json", "presentation.json"]) {
        const p = path.join(dp, fname)
        if (fs.existsSync(p)) {
          try {
            const deckJson = JSON.parse(fs.readFileSync(p, "utf-8"))
            name = deckJson.name || deckId
            isHtml = deckJson.outputFormat === "html"
          } catch {}
          break
        }
      }
      let slideCount = 0
      const slidesDir = path.join(dp, "slides")
      if (fs.existsSync(slidesDir)) {
        slideCount = fs.readdirSync(slidesDir).filter(f => f.endsWith(isHtml ? ".html" : ".json")).length
      }
      let thumbnailUrl: string | null = null
      const previewDir = path.join(dp, "preview")
      if (fs.existsSync(previewDir)) {
        const files = fs.readdirSync(previewDir).sort()
        const first = files.find(f => f.endsWith(".png"))
        // HTML decks have no PNG previews: fall back to a static HTML preview, slide 1
        // of the outline when it has one (as in cloud), else the first by name.
        const htmlPreviews = first ? [] : files.filter(f => /^[a-z0-9][a-z0-9_-]*\.html$/.test(f))
        const firstHtml = htmlPreviews.length === 0 ? undefined : (() => {
          let outline = ""
          try { outline = fs.readFileSync(path.join(dp, "specs", "outline.md"), "utf-8") } catch {}
          const slug = outline.split("\n").map(l => /^-\s*\[([a-z0-9-]+)\]/.exec(l)?.[1])
            .find(s => s && htmlPreviews.includes(`${s}.html`))
          return slug ? `${slug}.html` : htmlPreviews[0]
        })()
        if (first) thumbnailUrl = `/api/preview/${deckId}/preview/${first}`
        else if (firstHtml) {
          const mtime = Math.floor(fs.statSync(path.join(previewDir, firstHtml)).mtimeMs)
          thumbnailUrl = `/api/preview/${deckId}/preview/${firstHtml}?v=${mtime}`
        }
      }
      const pptxPath = path.join(dp, "output.pptx")
      const pptxUrl = fs.existsSync(pptxPath) ? `/api/preview/${deckId}/output.pptx` : null
      return { deckId, name, slideCount, updatedAt: new Date().toISOString(), thumbnailUrl, pptxUrl }
    })
    .sort((a, b) => b.deckId.localeCompare(a.deckId))

  return Response.json({ decks, favoriteIds })
}
