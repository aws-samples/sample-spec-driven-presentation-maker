// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Change request texts for the Local API route, read from the repository's
 * `shared/review_template.json` (the file the Cloud API reads through `shared/review.py`).
 * Local mode always runs from a checkout with `web-ui/` as the working directory.
 */

import fs from "fs"
import path from "path"
import type { ReviewTemplate } from "@/lib/review/schema"

export const REVIEW_TEMPLATE_PATH = path.resolve(process.cwd(), "..", "shared", "review_template.json")

let cached: ReviewTemplate | null = null

export function loadReviewTemplate(): ReviewTemplate {
  if (!cached) {
    const data = JSON.parse(fs.readFileSync(REVIEW_TEMPLATE_PATH, "utf-8")) as Partial<ReviewTemplate>
    if (!Array.isArray(data.message) || !data.message.every(l => typeof l === "string") || typeof data.guide !== "string") {
      throw new Error(`Invalid review template: ${REVIEW_TEMPLATE_PATH}`)
    }
    cached = { message: data.message, guide: data.guide }
  }
  return cached
}
