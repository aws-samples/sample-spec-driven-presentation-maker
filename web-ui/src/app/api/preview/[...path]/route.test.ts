// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local preview route: the two HTML paths it serves carry a CSP sandbox, every other
 * HTML path and every path outside the deck is refused.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

type Route = typeof import("./route")

let root: string
let GET: Route["GET"]
let savedRoot: string | undefined

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

function write(rel: string, data: string | Buffer) {
  const file = path.join(root, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, data)
}

function get(...segments: string[]) {
  return GET(new Request("http://localhost/api/preview"), { params: Promise.resolve({ path: segments }) })
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-preview-route-"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  write("d1/output.html", "<!doctype html><title>deck</title>")
  write("d1/preview/cover.html", "<!doctype html><title>cover</title>")
  write("d1/specs/x.html", "<!doctype html><title>spec</title>")
  write("d1/preview/png/cover.png", PNG)
  write("other.html", "<!doctype html>")
  vi.resetModules()
  GET = (await import("./route")).GET
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(root, { recursive: true, force: true })
})

describe("GET /api/preview/[...path]", () => {
  it("serves output.html in a sandbox that allows scripts and popups only", async () => {
    const res = await get("d1", "output.html")
    expect(res.status).toBe(200)
    expect(res.headers.get("Content-Security-Policy")).toBe("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox")
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff")
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8")
    expect(await res.text()).toContain("<title>deck</title>")
  })

  it("serves a slide preview in a sandbox without scripts", async () => {
    const res = await get("d1", "preview", "cover.html")
    expect(res.status).toBe(200)
    expect(res.headers.get("Content-Security-Policy")).toBe("sandbox")
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff")
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8")
  })

  it("refuses every other HTML path", async () => {
    expect((await get("d1", "specs", "x.html")).status).toBe(404)
    expect((await get("d1", "preview", "..", "output.html")).status).toBe(404)
  })

  it("refuses paths outside the deck", async () => {
    expect((await get("d1", "..", "other.html")).status).toBe(403)
    expect((await get("..", "other.html")).status).toBe(403)
  })

  it("serves a PNG as image/png", async () => {
    const res = await get("d1", "preview", "png", "cover.png")
    expect(res.status).toBe(200)
    expect(res.headers.get("Content-Type")).toBe("image/png")
    expect(Buffer.from(await res.arrayBuffer()).equals(PNG)).toBe(true)
  })
})
