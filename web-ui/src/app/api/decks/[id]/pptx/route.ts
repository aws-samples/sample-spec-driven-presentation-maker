// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local PPTX download — serves a deck's output.pptx as an attachment named after the
 * deck title (`<name>.pptx`), the Local counterpart of the cloud `GET /decks/{id}/pptx`.
 * `?notes=without` serves a copy without speaker notes, made by the engine
 * (`sdpm.engine.notes.strip_speaker_notes`, through `uv run`) in a temp directory that is
 * removed after the response is read; the stored file is never changed.
 * 404 when the deck has no output.pptx or is an HTML deck.
 * Local mode only.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { execFile } from "child_process"
import { resolveDeckDir } from "@/lib/local/deck-paths"
import { resolveWithin } from "@/lib/local/contained"
import { attachmentDisposition } from "@/lib/local/downloadName"
import { SDPM_ROOT } from "@/lib/local/sdpmPaths"

const PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
/** servers/local directory (uv-managed venv with sdpm deps). */
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
const STRIP_TIMEOUT_MS = 60_000
const STRIP_SCRIPT = [
  "import sys",
  "sys.path.insert(0, sys.argv[1])",
  "from sdpm.engine.notes import strip_speaker_notes",
  "strip_speaker_notes(sys.argv[2], sys.argv[3])",
].join("\n")

/** `src` without speaker notes, as bytes (the engine writes it to a temp file). */
async function withoutSpeakerNotes(src: string): Promise<Buffer<ArrayBuffer>> {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-pptx-"))
  try {
    const dst = path.join(dir, "output.pptx") // nosemgrep: path-join-resolve-traversal — fixed name in a fresh temp dir
    await new Promise<void>((resolve, reject) => {
      execFile(
        "uv",
        ["run", "--directory", MCP_LOCAL_DIR, "python", "-c", STRIP_SCRIPT, SDPM_ROOT, src, dst],
        { cwd: MCP_LOCAL_DIR, timeout: STRIP_TIMEOUT_MS },
        (err) => (err ? reject(err) : resolve()),
      )
    })
    return fs.readFileSync(dst)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

function readDeckJson(dp: string): Record<string, unknown> {
  for (const fname of ["deck.json", "presentation.json"]) {
    const p = resolveWithin(dp, fname)
    if (!p || !fs.existsSync(p)) continue
    try {
      const data = JSON.parse(fs.readFileSync(p, "utf-8"))
      return data && typeof data === "object" ? data : {}
    } catch {
      return {}
    }
  }
  return {}
}

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: deckId } = await params
  const dp = resolveDeckDir(deckId)
  if (!dp) return new Response("Not found", { status: 404 })
  const pptxPath = resolveWithin(dp, "output.pptx")
  const deckJson = readDeckJson(dp)
  if (deckJson.outputFormat === "html" || !pptxPath || !fs.existsSync(pptxPath)) return new Response("Not found", { status: 404 })

  let body: Buffer<ArrayBuffer>
  if (new URL(req.url).searchParams.get("notes") === "without") {
    try {
      body = await withoutSpeakerNotes(pptxPath)
    } catch (e) {
      console.warn("[pptx] could not remove speaker notes:", e)
      return new Response("Could not remove speaker notes", { status: 500 })
    }
  } else {
    body = fs.readFileSync(pptxPath)
  }

  return new Response(body, {
    headers: {
      "Content-Type": PPTX_TYPE,
      "Content-Disposition": attachmentDisposition(deckJson.name || deckId, ".pptx"),
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "no-cache",
    },
  })
}
