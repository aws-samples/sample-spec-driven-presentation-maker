// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local change request route: POST validates, writes `reviews/<id>.json` and returns the chat
 * message; cross-site requests, unknown decks and bad bodies are refused before any write.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"
import { MAX_BODY_BYTES } from "@/lib/review/schema"
import { parseReviewMessage } from "@/lib/review/marker"
import { loadReviewTemplate } from "@/lib/local/reviewTemplate"

type PostRoute = typeof import("./route")

let root: string
let savedRoot: string | undefined
let POST: PostRoute["POST"]

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
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
})

describe("POST /api/decks/[id]/reviews", () => {
  it("writes what was sent plus the guide and returns the message", async () => {
    const res = await post("d1", {
      note: "全体的に",
      comments: [comment({ status: "done" }), comment({ name: "B", slide: "intro", rect: [0, 0, 1280, 720], text: "見出し" })],
    }, { origin: "http://localhost" })
    expect(res.status).toBe(200)
    const { id, message } = await res.json()
    expect(id).toMatch(/^\d{8}-\d{6}-[0-9a-f]{4}$/)
    const stored = JSON.parse(fs.readFileSync(path.join(root, "d1", "reviews", `${id}.json`), "utf-8"))
    expect(stored).toEqual({
      id, note: "全体的に", slide_size: [1280, 720], guide: loadReviewTemplate().guide,
      comments: [comment(), comment({ name: "B", slide: "intro", rect: [0, 0, 1280, 720], text: "見出し" })],
    })
    expect(message).toContain(`reviews/${id}.json`)
    expect(parseReviewMessage(message)).toEqual({ id, note: "全体的に", comments: stored.comments })
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
