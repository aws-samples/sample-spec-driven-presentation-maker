// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Deck Detail API — reads a single deck from filesystem.
 * Local mode only.
 */



import fs from "fs"
import path from "path"
import os from "os"

const DECK_ROOT = path.join(os.homedir(), "Documents", "SDPM-Presentations")

function safeRead(p: string): string | null {
  try { return fs.existsSync(p) ? fs.readFileSync(p, "utf-8") : null } catch { return null }
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: deckId } = await params
  const dp = path.join(DECK_ROOT, deckId)
  if (!fs.existsSync(dp)) return new Response("Not found", { status: 404 })

  // Read deck metadata
  let deckJson: Record<string, unknown> = {}
  for (const fname of ["deck.json", "presentation.json"]) {
    const p = path.join(dp, fname)
    if (fs.existsSync(p)) { deckJson = JSON.parse(fs.readFileSync(p, "utf-8")); break }
  }

  // Index compose files by slug → latest epoch
  const composeBySlug = new Map<string, string>()
  let defsFilename: string | null = null
  const composeDir = path.join(dp, "compose")
  if (fs.existsSync(composeDir)) {
    const epochOf = (n: string) => { const m = n.match(/_(\d+)\.json$/); return m ? parseInt(m[1]) : 0 }
    let defsEpoch = -1
    for (const n of fs.readdirSync(composeDir)) {
      if (!n.endsWith(".json")) continue
      if (n.startsWith("defs_")) { const e = epochOf(n); if (e > defsEpoch) { defsEpoch = e; defsFilename = n }; continue }
      const m = n.match(/^(.+)_(\d+)\.json$/)
      if (!m) continue
      const [, slug, epochStr] = m
      const cur = composeBySlug.get(slug)
      if (!cur || epochOf(cur) < parseInt(epochStr)) composeBySlug.set(slug, n)
    }
  }

  // Parse outline for slug order
  const specsDir = path.join(dp, "specs")
  const outlineText = safeRead(path.join(specsDir, "outline.md"))
  const outlineSlugs = outlineText
    ? outlineText.split("\n").map(l => /^-\s*\[([a-z0-9-]+)\]/.exec(l)?.[1]).filter((s): s is string => !!s)
    : []

  // Index preview PNGs
  const previewByPage = new Map<number, string>()
  const previewDir = path.join(dp, "preview")
  if (fs.existsSync(previewDir)) {
    for (const f of fs.readdirSync(previewDir)) {
      if (!f.endsWith(".png")) continue
      const m = f.match(/^page(\d+)[-.]/); if (m) previewByPage.set(parseInt(m[1]), f)
    }
  }

  // Build slides array
  const slidesDir = path.join(dp, "slides")
  const slides: Record<string, unknown>[] = []
  let slugList = outlineSlugs.length > 0 ? outlineSlugs
    : (fs.existsSync(slidesDir) ? fs.readdirSync(slidesDir).filter(f => f.endsWith(".json")).map(f => f.replace(".json", "")) : [])
  const anyCompose = composeBySlug.size > 0
  let pageNum = 0
  if (anyCompose && fs.existsSync(slidesDir)) {
    for (const slug of slugList) {
      if (!fs.existsSync(path.join(slidesDir, `${slug}.json`))) continue
      pageNum++
      const composeFile = composeBySlug.get(slug)
      if (!composeFile) continue
      const previewFile = previewByPage.get(pageNum)
      slides.push({
        slug,
        previewUrl: previewFile ? `/api/preview/${deckId}/preview/${previewFile}` : null,
        composeUrl: `/api/preview/${deckId}/compose/${composeFile}`,
        updatedAt: new Date().toISOString(),
      })
    }
  }

  // Read specs
  let specs = null
  const brief = safeRead(path.join(specsDir, "brief.md"))
  const outline = safeRead(path.join(specsDir, "outline.md"))
  const artDirection = safeRead(path.join(specsDir, "art-direction.html")) || safeRead(path.join(specsDir, "art-direction.md"))
  if (brief || outline || artDirection) specs = { brief, outline, artDirection }

  const pptxPath = path.join(dp, "output.pptx")

  return Response.json({
    deckId,
    name: deckJson.name || deckId,
    slideOrder: deckJson.slideOrder || [],
    slides,
    defsUrl: defsFilename ? `/api/preview/${deckId}/compose/${defsFilename}` : null,
    pptxUrl: fs.existsSync(pptxPath) ? `/api/preview/${deckId}/output.pptx` : null,
    specs,
    updatedAt: new Date().toISOString(),
    chatSessionId: deckJson.chatSessionId,
    visibility: "private",
    isOwner: true,
    collaborators: [],
    collaboratorAliases: {},
  })
}
