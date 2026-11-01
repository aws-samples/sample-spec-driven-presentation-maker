// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local deck detail route: slideSize is returned for every deck (the comment tool needs it
 * for PPTX decks too), defaulting to 1920x1080.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/local/acp-process", () => ({ readOriginFromDeck: () => null }))

type Route = typeof import("./route")

let root: string
let savedRoot: string | undefined
let GET: Route["GET"]

function write(rel: string, data: string) {
  const file = path.join(root, rel) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, data)
}

async function deck(deckId: string) {
  const res = await GET(new Request(`http://localhost/api/decks/${deckId}`), { params: Promise.resolve({ id: deckId }) })
  return res.json()
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-deck-route-"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  write("pptx/deck.json", JSON.stringify({ name: "P", slideSize: { width: 1280, height: 720 } }))
  write("pptx/slides/intro.json", "{}")
  write("plain/deck.json", JSON.stringify({ name: "Q" }))
  write("html/deck.json", JSON.stringify({ name: "H", outputFormat: "html", slideSize: { width: 1600, height: 900 } }))
  vi.resetModules()
  GET = (await import("./route")).GET
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
})

describe("GET /api/decks/[id] slideSize", () => {
  it("returns deck.json slideSize for a PPTX deck", async () => {
    const body = await deck("pptx")
    expect(body.outputFormat).toBeUndefined()
    expect(body.slideSize).toEqual({ width: 1280, height: 720 })
  })

  it("defaults to 1920x1080", async () => {
    expect((await deck("plain")).slideSize).toEqual({ width: 1920, height: 1080 })
  })

  it("keeps slideSize for an HTML deck", async () => {
    const body = await deck("html")
    expect(body.outputFormat).toBe("html")
    expect(body.slideSize).toEqual({ width: 1600, height: 900 })
  })
})
