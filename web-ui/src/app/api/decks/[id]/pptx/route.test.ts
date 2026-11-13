// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local PPTX download: output.pptx as an attachment named after the deck title. */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

type Route = typeof import("./route")

let root: string
let GET: Route["GET"]
let savedRoot: string | undefined

function write(rel: string, data: string) {
  const file = path.join(root, rel) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, data)
}

function get(id: string) {
  return GET(new Request(`http://localhost/api/decks/${id}/pptx`), { params: Promise.resolve({ id }) })
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-pptx-route-"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  write("jp/deck.json", JSON.stringify({ name: "四半期レビュー" }))
  write("jp/output.pptx", "PK")
  write("evil/deck.json", JSON.stringify({ name: "x\"\r\nSet-Cookie: a=b" }))
  write("evil/output.pptx", "PK")
  write("noname/output.pptx", "PK")
  write("unbuilt/deck.json", JSON.stringify({ name: "Draft" }))
  write("html/deck.json", JSON.stringify({ name: "Web", outputFormat: "html" }))
  write("html/output.pptx", "PK")
  write("linked/deck.json", JSON.stringify({ name: "Linked" }))
  fs.writeFileSync(`${root}-outside.pptx`, "PK")
  fs.symlinkSync(`${root}-outside.pptx`, path.join(root, "linked", "output.pptx"))
  vi.resetModules()
  GET = (await import("./route")).GET
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
  fs.rmSync(`${root}-outside.pptx`, { force: true })
})

describe("GET /api/decks/[id]/pptx", () => {
  it("serves output.pptx as an attachment named after the title", async () => {
    const res = await get("jp")
    expect(res.status).toBe(200)
    expect(res.headers.get("Content-Type")).toBe("application/vnd.openxmlformats-officedocument.presentationml.presentation")
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff")
    expect(res.headers.get("Content-Disposition")).toBe(
      "attachment; filename=\"deck.pptx\"; filename*=UTF-8''%E5%9B%9B%E5%8D%8A%E6%9C%9F%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC.pptx",
    )
    expect(await res.text()).toBe("PK")
  })

  it("keeps a hostile title inside one header", async () => {
    const res = await get("evil")
    expect(res.status).toBe(200)
    expect(res.headers.get("Set-Cookie")).toBeNull()
    expect(res.headers.get("Content-Disposition")).toBe(
      "attachment; filename=\"xSet-Cookie: a=b.pptx\"; filename*=UTF-8''xSet-Cookie%3A%20a%3Db.pptx",
    )
  })

  it("falls back to the deck id without a deck.json", async () => {
    const res = await get("noname")
    expect(res.headers.get("Content-Disposition")).toMatch(/^attachment; filename="noname\.pptx"/)
  })

  it("is 404 without output.pptx, for an HTML deck, outside the root and for a link leaving it", async () => {
    expect((await get("unbuilt")).status).toBe(404)
    expect((await get("html")).status).toBe(404)
    expect((await get("..")).status).toBe(404)
    expect((await get("missing")).status).toBe(404)
    expect((await get("linked")).status).toBe(404)
  })
})
