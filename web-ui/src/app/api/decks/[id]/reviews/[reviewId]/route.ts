// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local review request read API — returns `reviews/<id>.json` (status and replies the agent wrote).
 * Local mode only. Mirrors the cloud Lambda `GET /decks/{id}/reviews/{reviewId}`.
 */

import fs from "fs"
import { resolveDeckPath } from "@/lib/local/deck-paths"
import { rejectCrossSite } from "@/lib/local/requestGuard"
import { isReviewId } from "@/lib/review/schema"

export async function GET(req: Request, { params }: { params: Promise<{ id: string; reviewId: string }> }) {
  const refused = rejectCrossSite(req)
  if (refused) return refused

  const { id: deckId, reviewId } = await params
  if (!isReviewId(reviewId)) return Response.json({ error: "Invalid review id" }, { status: 400 })

  const file = resolveDeckPath(deckId, "reviews", `${reviewId}.json`)
  if (!file || !fs.existsSync(file)) return Response.json({ error: "Review not found" }, { status: 404 })
  let data: unknown
  try {
    data = JSON.parse(fs.readFileSync(file, "utf-8"))
  } catch {
    return Response.json({ error: "Review not found" }, { status: 404 })
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return Response.json({ error: "Review not found" }, { status: 404 })
  }
  return Response.json(data)
}
