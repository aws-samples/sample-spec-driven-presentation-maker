// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Deck Detail API — reads a single deck from filesystem.
 * Local mode only.
 */



import fs from "fs"
import path from "path"
import { resolveDeckDir, readSlideSize, DECK_ROOT } from "@/lib/local/deck-paths"
import { readOriginFromDeck } from "@/lib/local/acp-process"
import { resolveWithin } from "@/lib/local/contained"
import { inlineStyleIcons } from "@/lib/local/styleIcons"

/** Text of a file under the deck directory; null when missing, unreadable or outside it. */
function safeRead(dp: string, ...segments: string[]): string | null {
  const p = resolveWithin(dp, ...segments)
  try { return p && fs.existsSync(p) ? fs.readFileSync(p, "utf-8") : null } catch { return null }
}

// Copies of the Python definitions, pinned by tests/test_slug_parity.py.
/** Slug grammar of HTML slide files (`slides/<slug>.html`): `SLUG_RE` in sdpm.engine.schema. */
const HTML_SLUG_RE = /^[a-z0-9][a-z0-9_-]*$/
/** A slide line of outline.md: `OUTLINE_ENTRY_RE` in sdpm.engine.schema. */
const OUTLINE_ENTRY_RE = /^-\s*\[([a-z0-9-]+)\]/
/** `compose/<slug>_<epoch>.json` (slug "defs" is the deck's defs): `COMPOSE_NAME_RE` in shared/artifact_keys.py. */
const COMPOSE_FILE_RE = /^(.+)_(\d+)\.json$/
/** Local preview image of a slide, `preview/<slug>.png` (outline slug). */
const PREVIEW_PNG_RE = /^([a-z0-9-]+)\.png$/

/** `?v=<mtime>` cache-buster so the UI sees a rebuilt file as a new URL; null when absent. */
function versionedUrl(filePath: string, url: string): string | null {
  try { return `${url}?v=${Math.floor(fs.statSync(filePath).mtimeMs)}` } catch { return null }
}

/** HTML deck slides: `slides/<slug>.html` in outline order, previews from `preview/<slug>.html`. */
function htmlSlides(dp: string, deckId: string, outlineSlugs: string[]): Record<string, unknown>[] {
  // `dp` comes from resolveDeckDir (allow-list + realpath check); every slug passes HTML_SLUG_RE before it is joined.
  const slidesDir = path.join(dp, "slides") // nosemgrep: path-join-resolve-traversal — dp validated by resolveDeckDir
  if (!fs.existsSync(slidesDir)) return []
  const slugList = outlineSlugs.length > 0 ? outlineSlugs
    : fs.readdirSync(slidesDir).filter(f => f.endsWith(".html")).map(f => f.slice(0, -".html".length)).sort()
  return slugList
    .filter(slug => HTML_SLUG_RE.test(slug) && fs.existsSync(path.join(slidesDir, `${slug}.html`))) // nosemgrep: path-join-resolve-traversal — slug checked by HTML_SLUG_RE first
    .map(slug => ({
      slug,
      previewUrl: versionedUrl(path.join(dp, "preview", `${slug}.html`), `/api/preview/${deckId}/preview/${slug}.html`), // nosemgrep: path-join-resolve-traversal — slug passed HTML_SLUG_RE above
      composeUrl: null,
      updatedAt: new Date().toISOString(),
    }))
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: deckId } = await params
  const dp = resolveDeckDir(deckId)
  if (!dp || !fs.existsSync(dp)) return new Response("Not found", { status: 404 })

  // Read deck metadata
  let deckJson: Record<string, unknown> = {}
  for (const fname of ["deck.json", "presentation.json"]) {
    const p = resolveWithin(dp, fname)
    if (p && fs.existsSync(p)) { deckJson = JSON.parse(fs.readFileSync(p, "utf-8")); break }
  }

  // Index compose files by slug → latest epoch
  const composeBySlug = new Map<string, string>()
  let defsFilename: string | null = null
  const composeDir = path.join(dp, "compose")
  if (fs.existsSync(composeDir)) {
    const epochOf = (n: string) => { const m = n.match(COMPOSE_FILE_RE); return m ? parseInt(m[2]) : 0 }
    let defsEpoch = -1
    for (const n of fs.readdirSync(composeDir)) {
      if (!n.endsWith(".json")) continue
      if (n.startsWith("defs_")) { const e = epochOf(n); if (e > defsEpoch) { defsEpoch = e; defsFilename = n }; continue }
      const m = n.match(COMPOSE_FILE_RE)
      if (!m) continue
      const [, slug, epochStr] = m
      const cur = composeBySlug.get(slug)
      if (!cur || epochOf(cur) < parseInt(epochStr)) composeBySlug.set(slug, n)
    }
  }

  // Parse outline for slug order
  const outlineText = safeRead(dp, "specs", "outline.md")
  const outlineSlugs = outlineText
    ? outlineText.split("\n").map(l => OUTLINE_ENTRY_RE.exec(l)?.[1]).filter((s): s is string => !!s)
    : []

  // Index preview PNGs — supports both slug-named ({slug}.png) and legacy page-numbered (page{N}-*.png)
  const previewBySlug = new Map<string, string>()
  const previewByPage = new Map<number, string>()
  const previewDir = path.join(dp, "preview")
  if (fs.existsSync(previewDir)) {
    for (const f of fs.readdirSync(previewDir)) {
      if (!f.endsWith(".png")) continue
      const pageMatch = f.match(/^page(\d+)[-.]/); if (pageMatch) { previewByPage.set(parseInt(pageMatch[1]), f); continue }
      const slugMatch = f.match(PREVIEW_PNG_RE); if (slugMatch) previewBySlug.set(slugMatch[1], f)
    }
  }

  // Build slides array
  const isHtml = deckJson.outputFormat === "html"
  const slidesDir = path.join(dp, "slides")
  const slides: Record<string, unknown>[] = isHtml ? htmlSlides(dp, deckId, outlineSlugs) : []
  let slugList = outlineSlugs.length > 0 ? outlineSlugs
    : (fs.existsSync(slidesDir) ? fs.readdirSync(slidesDir).filter(f => f.endsWith(".json")).map(f => f.replace(".json", "")) : [])
  let pageNum = 0
  if (!isHtml && fs.existsSync(slidesDir)) {
    for (const slug of slugList) {
      if (!fs.existsSync(path.join(slidesDir, `${slug}.json`))) continue
      pageNum++
      const composeFile = composeBySlug.get(slug)
      const previewFile = previewBySlug.get(slug) || previewByPage.get(pageNum)
      slides.push({
        slug,
        previewUrl: previewFile ? `/api/preview/${deckId}/preview/${previewFile}` : null,
        composeUrl: composeFile ? `/api/preview/${deckId}/compose/${composeFile}` : null,
        updatedAt: new Date().toISOString(),
      })
    }
  }

  // Read specs
  let specs = null
  const brief = safeRead(dp, "specs", "brief.md")
  const outline = safeRead(dp, "specs", "outline.md")
  // The deck's style copy is shown in the Web UI: draw the catalog icons it references
  const artHtml = safeRead(dp, "specs", "art-direction.html")
  const artDirection = artHtml ? (await inlineStyleIcons([artHtml]))[0] : safeRead(dp, "specs", "art-direction.md")
  if (brief || outline || artDirection) specs = { brief, outline, artDirection }

  const pptxPath = path.join(dp, "output.pptx")
  const sessionOrigin = readOriginFromDeck(deckId)

  return Response.json({
    deckId,
    name: deckJson.name || deckId,
    slideOrder: deckJson.slideOrder || [],
    slides,
    template: deckJson.template || null,
    defsUrl: defsFilename ? `/api/preview/${deckId}/compose/${defsFilename}` : null,
    pptxUrl: fs.existsSync(pptxPath) ? `/api/preview/${deckId}/output.pptx` : null,
    specs,
    updatedAt: new Date().toISOString(),
    chatSessionId: safeRead(dp, ".session")?.trim() || null,
    ...(sessionOrigin ? { sessionOrigin } : {}),
    visibility: "private",
    isOwner: true,
    slideSize: readSlideSize(deckJson),
    ...(isHtml ? {
      outputFormat: "html",
      htmlUrl: versionedUrl(path.join(dp, "output.html"), `/api/preview/${deckId}/output.html`),
    } : {}),
  })
}

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: deckId } = await params
  const dp = resolveDeckDir(deckId)
  if (!dp || !fs.existsSync(dp)) return new Response("Not found", { status: 404 })

  fs.rmSync(dp, { recursive: true, force: true })

  // Remove from decks.json index if present
  const indexPath = resolveWithin(DECK_ROOT, "decks.json") // null: a symlink leading out of the deck root
  if (indexPath && fs.existsSync(indexPath)) {
    try {
      const index = JSON.parse(fs.readFileSync(indexPath, "utf-8"))
      if (Array.isArray(index.decks)) {
        index.decks = index.decks.filter((d: { deckId?: string }) => d.deckId !== deckId)
        fs.writeFileSync(indexPath, JSON.stringify(index, null, 2))
      }
    } catch { /* index file corrupt — skip */ }
  }

  return Response.json({ deleted: true })
}
