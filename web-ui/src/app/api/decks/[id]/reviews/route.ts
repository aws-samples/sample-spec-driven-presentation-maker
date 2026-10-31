// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local review request API — creates `reviews/<id>.json` for a deck on the filesystem.
 * Local mode only. Mirrors the cloud Lambda `POST /decks/{id}/reviews`.
 */

import fs from "fs"
import path from "path"
import { readSlideSize, resolveDeckDir } from "@/lib/local/deck-paths"
import { rejectCrossSite } from "@/lib/local/requestGuard"
import { buildReviewFile, createdAtIso, MAX_BODY_BYTES, newReviewId, validateReviewSubmission } from "@/lib/review/schema"

function readDeckJson(dp: string): Record<string, unknown> {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(dp, "deck.json"), "utf-8")) as unknown // nosemgrep: path-join-resolve-traversal — dp validated by resolveDeckDir
    return typeof data === "object" && data !== null && !Array.isArray(data) ? data as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const refused = rejectCrossSite(req, { requireJson: true })
  if (refused) return refused

  const { id: deckId } = await params
  const dp = resolveDeckDir(deckId)
  if (!dp || !fs.existsSync(dp)) return Response.json({ error: "Deck not found" }, { status: 404 })

  const raw = await req.text()
  if (Buffer.byteLength(raw, "utf-8") > MAX_BODY_BYTES) {
    return Response.json({ error: `body exceeds ${MAX_BODY_BYTES} bytes` }, { status: 413 })
  }
  let body: unknown
  try {
    body = JSON.parse(raw)
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 })
  }

  const { width, height } = readSlideSize(readDeckJson(dp))
  const size: [number, number] = [Math.floor(width), Math.floor(height)]
  // `dp` comes from resolveDeckDir; the validator only asks about slugs that passed SLUG_RE.
  const slidesDir = path.join(dp, "slides") // nosemgrep: path-join-resolve-traversal — dp validated by resolveDeckDir
  const slugExists = (slug: string) =>
    fs.existsSync(path.join(slidesDir, `${slug}.json`)) || fs.existsSync(path.join(slidesDir, `${slug}.html`)) // nosemgrep: path-join-resolve-traversal — slug checked by SLUG_RE first
  const result = validateReviewSubmission(body, size, slugExists)
  if (!result.ok) return Response.json({ error: result.error }, { status: 400 })

  const reviewsDir = path.join(dp, "reviews") // nosemgrep: path-join-resolve-traversal — dp validated by resolveDeckDir
  fs.mkdirSync(reviewsDir, { recursive: true })
  for (let attempt = 0; attempt < 3; attempt++) {
    const now = new Date()
    const reviewId = newReviewId(now)
    const file = buildReviewFile(reviewId, createdAtIso(now), size, result.value)
    try {
      // "wx" fails when the id is already taken, so an existing request is never overwritten.
      fs.writeFileSync(path.join(reviewsDir, `${reviewId}.json`), JSON.stringify(file, null, 2) + "\n", { encoding: "utf-8", flag: "wx" }) // nosemgrep: path-join-resolve-traversal — reviewId generated server-side
      return Response.json(file)
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e
    }
  }
  return Response.json({ error: "Could not allocate a review id" }, { status: 409 })
}
