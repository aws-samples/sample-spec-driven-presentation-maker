// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local PPTX download without speaker notes, through the real engine (`uv run`). Skipped
 * where uv is not on PATH (the web-ui CI job); the fake-engine cases are in route.test.ts.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { spawnSync } from "child_process"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

type Route = typeof import("./route")

const hasUv = spawnSync("uv", ["--version"]).status === 0
const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
const TEMPLATE = path.resolve(process.cwd(), "..", "sdpm", "templates", "blank-dark.pptx")

/** Run python with python-pptx (the servers/local environment); returns stdout. */
function python(script: string, ...args: string[]): string {
  const res = spawnSync("uv", ["run", "--directory", MCP_LOCAL_DIR, "python", "-c", script, ...args], {
    cwd: MCP_LOCAL_DIR,
    encoding: "utf-8",
    timeout: 120_000,
  })
  if (res.status !== 0) throw new Error(`python failed: ${res.stderr}`)
  return res.stdout
}

const MAKE_DECK = [
  "import sys",
  "from pptx import Presentation",
  "prs = Presentation(sys.argv[1])",
  "for text in ('Presenter script one.', 'Presenter script two.'):",
  "    slide = prs.slides.add_slide(prs.slide_layouts[0])",
  "    slide.notes_slide.notes_text_frame.text = text",
  "prs.save(sys.argv[2])",
].join("\n")

const COUNT_NOTES = [
  "import sys",
  "from pptx import Presentation",
  "prs = Presentation(sys.argv[1])",
  "print(len(prs.slides), sum(1 for s in prs.slides if s.has_notes_slide))",
].join("\n")

let root: string
let savedRoot: string | undefined
let GET: Route["GET"]

function get(query: string) {
  return GET(new Request(`http://localhost/api/decks/notes/pptx${query}`), { params: Promise.resolve({ id: "notes" }) })
}

/** "<slides> <slides with a notes slide>" of a downloaded body. */
async function countNotes(res: Response): Promise<{ data: Buffer; counts: string }> {
  const data = Buffer.from(await res.arrayBuffer())
  const file = path.join(root, "downloaded.pptx") // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.writeFileSync(file, data)
  return { data, counts: python(COUNT_NOTES, file).trim() }
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-pptx-engine-"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  if (hasUv) {
    fs.mkdirSync(path.join(root, "notes"))
    fs.writeFileSync(path.join(root, "notes", "deck.json"), JSON.stringify({ name: "Notes" }))
    python(MAKE_DECK, TEMPLATE, path.join(root, "notes", "output.pptx"))
  }
  vi.resetModules()
  GET = (await import("./route")).GET
}, 120_000)

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
})

describe("GET /api/decks/[id]/pptx through the engine", () => {
  it.skipIf(!hasUv)("serves a copy without speaker notes; the plain download keeps them", async () => {
    const plain = await countNotes(await get(""))
    const [slides, withNotes] = plain.counts.split(" ").map(Number)
    expect(withNotes).toBeGreaterThanOrEqual(2)  // the template's own slides may carry notes too
    expect(plain.data.includes("ppt/notesSlides/")).toBe(true)

    const res = await get("?notes=without")
    expect(res.status).toBe(200)
    const stripped = await countNotes(res)
    expect(stripped.counts).toBe(`${slides} 0`)
    expect(stripped.data.includes("ppt/notesSlides/")).toBe(false)
  }, 120_000)
})
