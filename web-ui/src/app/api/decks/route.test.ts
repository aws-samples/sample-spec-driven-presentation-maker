// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local deck list: hasPptx is true only for a PPTX deck with a built output.pptx, and no URL is listed. */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

let root: string
let savedRoot: string | undefined
let GET: typeof import("./route")["GET"]

function write(rel: string, data: string) {
  const file = path.join(root, rel) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, data)
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-deck-list-"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  write("built/deck.json", JSON.stringify({ name: "Built" }))
  write("built/output.pptx", "PK")
  write("draft/deck.json", JSON.stringify({ name: "Draft" }))
  write("web/deck.json", JSON.stringify({ name: "Web", outputFormat: "html" }))
  write("web/output.pptx", "PK")
  vi.resetModules()
  GET = (await import("./route")).GET
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
})

describe("GET /api/decks (local)", () => {
  it("flags the decks that can be downloaded as PPTX", async () => {
    const { decks } = await (await GET()).json()
    const byId = Object.fromEntries(decks.map((d: { deckId: string }) => [d.deckId, d]))
    expect(byId.built.hasPptx).toBe(true)
    expect(byId.draft.hasPptx).toBe(false)
    expect(byId.web.hasPptx).toBe(false)
    expect(decks.every((d: Record<string, unknown>) => !("pptxUrl" in d))).toBe(true)
  })
})
