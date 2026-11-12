// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local preview route: the two HTML paths it serves carry a CSP sandbox, every other
 * HTML path and every path outside the deck is refused, and every other file is served
 * with nosniff and a CSP that keeps it inert if opened as a document.
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
const FILE_CSP = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"

function write(rel: string, data: string | Buffer) {
  const file = path.join(root, rel) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
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
  write("d1/attachments/imports/k/extracted/images/logo.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
  write("d1/compose/defs.json", '{"version":1,"defs":""}')
  write("d1/output.pptx", "PK")
  write("d1/notes.txt", "x")
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

  it.each([
    [["preview", "png", "cover.png"], "image/png"],
    [["attachments", "imports", "k", "extracted", "images", "logo.svg"], "image/svg+xml"],
    [["compose", "defs.json"], "application/json"],
    [["output.pptx"], "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
  ])("serves %j with nosniff and an inert-document CSP", async (rest, type) => {
    const res = await get("d1", ...rest)
    expect(res.status).toBe(200)
    expect(res.headers.get("Content-Type")).toBe(type)
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff")
    expect(res.headers.get("Content-Security-Policy")).toBe(FILE_CSP)
  })

  it("keeps the file CSP sandboxed, script-free and offline", () => {
    const directives = FILE_CSP.split(";").map((d) => d.trim())
    expect(directives).toContain("sandbox")
    expect(directives).toContain("default-src 'none'")
    expect(FILE_CSP).not.toMatch(/script-src|allow-scripts|https?:/)
  })

  it("refuses file types it does not list", async () => {
    expect((await get("d1", "notes.txt")).status).toBe(404)
  })
})
