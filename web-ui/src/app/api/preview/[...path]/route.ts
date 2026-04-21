// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local Preview File Server — serves deck assets (PNG, JSON, PPTX) from filesystem.
 * URL: /api/preview/{deckId}/{subpath...}
 * Local mode only.
 */



import fs from "fs"
import path from "path"
import os from "os"

const DECK_ROOT = path.join(os.homedir(), "Documents", "SDPM-Presentations")

const MIME: Record<string, string> = {
  ".png": "image/png",
  ".json": "application/json",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".svg": "image/svg+xml",
}

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const segments = (await params).path
  if (!segments || segments.length < 2) return new Response("Not found", { status: 404 })

  const filePath = path.join(DECK_ROOT, ...segments)

  // Prevent path traversal
  if (!filePath.startsWith(DECK_ROOT)) return new Response("Forbidden", { status: 403 })
  if (!fs.existsSync(filePath)) return new Response("Not found", { status: 404 })

  const ext = path.extname(filePath)
  const contentType = MIME[ext] || "application/octet-stream"
  const body = fs.readFileSync(filePath)

  return new Response(body, {
    headers: { "Content-Type": contentType, "Cache-Control": "no-cache" },
  })
}
