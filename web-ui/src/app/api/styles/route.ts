// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Styles API — lists styles from bundled + user-local directories with pin/source metadata. */
import { BUNDLED_STYLES_DIR, getUserStylesDir, getState, listStylesFromDir } from "@/lib/local/sdpmPaths"
import { inlineStyleIcons } from "@/lib/local/styleIcons"

export async function GET() {
  const userDir = getUserStylesDir()
  const pinnedNames: string[] = (getState().pinned_styles as string[]) || []
  const pinSet = new Set(pinnedNames)

  // Merge: user-local first (shadows bundled with same name)
  const seen = new Set<string>()
  const merged: Array<{ name: string; description: string; html: string; pinned: boolean; source: "builtin" | "user" }> = []

  for (const s of listStylesFromDir(userDir)) {
    seen.add(s.name)
    merged.push({ ...s, pinned: pinSet.has(s.name), source: "user" })
  }
  for (const s of listStylesFromDir(BUNDLED_STYLES_DIR)) {
    if (seen.has(s.name)) continue
    merged.push({ ...s, pinned: pinSet.has(s.name), source: "builtin" })
  }

  // Display copies: the catalog icons each style references, drawn in
  const shown = await inlineStyleIcons(merged.map(s => s.html))
  return Response.json({ styles: merged.map((s, i) => ({ ...s, html: shown[i] })) })
}
