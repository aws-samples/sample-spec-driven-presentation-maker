// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local PPTX download: output.pptx as an attachment named after the deck title, and
 * `?notes=without` through the engine (a fake `execFile` here; route.engine.test.ts runs
 * the real one).
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

type ExecCallback = (err: Error | null) => void
const { execFile } = vi.hoisted(() => ({ execFile: vi.fn() }))
vi.mock("child_process", () => ({ execFile, default: { execFile } }))

type Route = typeof import("./route")

let root: string
let GET: Route["GET"]
let savedRoot: string | undefined

function write(rel: string, data: string) {
  const file = path.join(root, rel) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, data)
}

function get(id: string, query = "") {
  return GET(new Request(`http://localhost/api/decks/${id}/pptx${query}`), { params: Promise.resolve({ id }) })
}

/** The engine writes its copy to the last argument. */
function engineWrites(data: string) {
  execFile.mockImplementation((_cmd: string, args: string[], _opts: unknown, cb: ExecCallback) => {
    fs.writeFileSync(args[args.length - 1], data)
    cb(null)
  })
}

beforeEach(() => {
  execFile.mockReset()
  engineWrites("PK-stripped")
})

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

  it("never runs the engine for the stored file", async () => {
    await get("jp")
    await get("jp", "?notes=with")
    expect(execFile).not.toHaveBeenCalled()
  })
})

describe("GET /api/decks/[id]/pptx?notes=without", () => {
  it("serves the engine's copy without speaker notes under the same headers", async () => {
    const res = await get("jp", "?notes=without")
    expect(res.status).toBe(200)
    expect(res.headers.get("Content-Type")).toBe("application/vnd.openxmlformats-officedocument.presentationml.presentation")
    expect(res.headers.get("Content-Disposition")).toMatch(/^attachment; filename="deck\.pptx"; filename\*=UTF-8''%E5%9B%9B/)
    expect(await res.text()).toBe("PK-stripped")

    expect(execFile).toHaveBeenCalledTimes(1)
    const [cmd, args, opts] = execFile.mock.calls[0] as [string, string[], { cwd: string }]
    expect(cmd).toBe("uv")
    expect(args.slice(0, 2)).toEqual(["run", "--directory"])
    expect(args[2]).toMatch(/[/\\]servers[/\\]local$/)
    expect(opts.cwd).toBe(args[2])
    expect(args[5]).toContain("from sdpm.engine.notes import strip_speaker_notes")
    expect(args[6]).toMatch(/[/\\]sdpm$/)
    expect(fs.realpathSync(args[7])).toBe(fs.realpathSync(path.join(root, "jp", "output.pptx")))
    // The temp copy is gone, the stored file unchanged
    expect(fs.existsSync(path.dirname(args[8]))).toBe(false)
    expect(fs.readFileSync(path.join(root, "jp", "output.pptx"), "utf-8")).toBe("PK")
  })

  it("is 500 when the engine fails, and removes its temp dir", async () => {
    execFile.mockImplementation((_cmd: string, args: string[], _opts: unknown, cb: ExecCallback) => {
      fs.writeFileSync(args[args.length - 1], "partial")
      cb(new Error("exit 1"))
    })
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const res = await get("jp", "?notes=without")
    expect(res.status).toBe(500)
    expect(await res.text()).toBe("Could not remove speaker notes")
    const args = execFile.mock.calls[0][1] as string[]
    expect(fs.existsSync(path.dirname(args[args.length - 1]))).toBe(false)
    warn.mockRestore()
  })

  it("stays 404 where the plain download is, without running the engine", async () => {
    for (const id of ["unbuilt", "html", "..", "missing", "linked"]) {
      expect((await get(id, "?notes=without")).status).toBe(404)
    }
    expect(execFile).not.toHaveBeenCalled()
  })
})
