// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local review routes: POST validates and writes `reviews/<id>.json`, GET reads it back;
 * cross-site requests, unknown decks and malformed ids are refused before any file access.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"
import { MAX_BODY_BYTES } from "@/lib/review/schema"

type PostRoute = typeof import("./route")
type GetRoute = typeof import("./[reviewId]/route")

let root: string
let savedRoot: string | undefined
let POST: PostRoute["POST"]
let GET: GetRoute["GET"]

function write(rel: string, data: string) {
  const file = path.join(root, rel) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, data)
}

const comment = (over: Record<string, unknown> = {}) =>
  ({ name: "A", slide: "sales", rect: [100, 50, 400, 200], text: "@B と同じ色で", ...over })

function post(deckId: string, body: unknown, headers: Record<string, string> = {}) {
  return POST(new Request(`http://localhost/api/decks/${deckId}/reviews`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  }), { params: Promise.resolve({ id: deckId }) })
}

function get(deckId: string, reviewId: string, headers: Record<string, string> = {}) {
  return GET(new Request(`http://localhost/api/decks/${deckId}/reviews/${reviewId}`, { headers }),
    { params: Promise.resolve({ id: deckId, reviewId }) })
}

const reviewFiles = () => {
  const dir = path.join(root, "d1", "reviews")
  return fs.existsSync(dir) ? fs.readdirSync(dir) : []
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-review-route-"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  write("d1/deck.json", JSON.stringify({ slideSize: { width: 1280, height: 720 } }))
  write("d1/slides/intro.json", "{}")
  write("d1/slides/sales.html", "<section></section>")
  vi.resetModules()
  POST = (await import("./route")).POST
  GET = (await import("./[reviewId]/route")).GET
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
})

describe("POST /api/decks/[id]/reviews", () => {
  it("writes the review file with server-computed refs and status", async () => {
    const res = await post("d1", {
      note: "全体的に",
      comments: [comment({ refs: ["Z"] }), comment({ name: "B", slide: "intro", rect: [0, 0, 1280, 720], text: "見出し" })],
    }, { origin: "http://localhost" })
    expect(res.status).toBe(200)
    const file = await res.json()
    expect(file.id).toMatch(/^\d{8}-\d{6}-[0-9a-f]{4}$/)
    expect(file.slide_size).toEqual([1280, 720])
    expect(file.comments[0]).toEqual({ ...comment(), refs: ["B"], status: "open", reply: null })
    expect(file.comments[1].refs).toEqual([])
    const stored = JSON.parse(fs.readFileSync(path.join(root, "d1", "reviews", `${file.id}.json`), "utf-8"))
    expect(stored).toEqual(file)
  })

  it.each([
    ["unknown slug", { comments: [comment({ slide: "missing" })] }],
    ["rect overflow", { comments: [comment({ rect: [1000, 0, 400, 100] })] }],
    ["101 comments", { comments: Array.from({ length: 101 }, (_, i) => comment({ name: String.fromCharCode(65 + (i % 26)).repeat(1 + Math.floor(i / 26)) })) }],
  ])("rejects %s with 400", async (_name, body) => {
    const before = reviewFiles().length
    expect((await post("d1", body)).status).toBe(400)
    expect(reviewFiles().length).toBe(before)
  })

  it("rejects invalid JSON with 400", async () => {
    expect((await post("d1", "{nope")).status).toBe(400)
  })

  it("rejects an oversize body with 413", async () => {
    expect((await post("d1", { note: "x".repeat(MAX_BODY_BYTES), comments: [comment()] })).status).toBe(413)
  })

  it("refuses a cross-site origin with 403", async () => {
    const before = reviewFiles().length
    expect((await post("d1", { comments: [comment()] }, { origin: "http://evil.example" })).status).toBe(403)
    expect((await post("d1", { comments: [comment()] }, { origin: "null" })).status).toBe(403)
    expect(reviewFiles().length).toBe(before)
  })

  it("refuses a non-JSON content type with 415", async () => {
    expect((await post("d1", JSON.stringify({ comments: [comment()] }), { "content-type": "text/plain" })).status).toBe(415)
  })

  it.each(["missing", "..", "../d1"])("returns 404 for deck %j", async deckId => {
    expect((await post(deckId, { comments: [comment()] })).status).toBe(404)
  })
})

describe("GET /api/decks/[id]/reviews/[reviewId]", () => {
  it.each(["../x", "20261101-102000-A1B2", "x.json"])("rejects id %j with 400", async id => {
    expect((await get("d1", id)).status).toBe(400)
  })

  it("returns 404 for a missing review or deck", async () => {
    expect((await get("d1", "20261101-102000-0000")).status).toBe(404)
    expect((await get("missing", "20261101-102000-0000")).status).toBe(404)
  })

  it("refuses a cross-site origin with 403", async () => {
    expect((await get("d1", "20261101-102000-0000", { origin: "http://evil.example" })).status).toBe(403)
  })

  it("round-trips a created review", async () => {
    const created = await (await post("d1", { comments: [comment()] })).json()
    const res = await get("d1", created.id)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual(created)
  })
})
