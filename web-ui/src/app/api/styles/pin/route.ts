// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local Pin API — toggle pin state for a style in state.json. */
import { getState, updateState } from "@/lib/local/sdpmPaths"

export async function POST(req: Request) {
  const { name, pinned } = await req.json() as { name: string; pinned: boolean }
  if (!name || typeof pinned !== "boolean") {
    return Response.json({ error: "name and pinned required" }, { status: 400 })
  }

  const current: string[] = (getState().pinned_styles as string[]) || []
  const updated = pinned
    ? [...new Set([...current, name])]
    : current.filter(n => n !== name)

  updateState("pinned_styles", updated)
  return Response.json({ pinned_styles: updated })
}
