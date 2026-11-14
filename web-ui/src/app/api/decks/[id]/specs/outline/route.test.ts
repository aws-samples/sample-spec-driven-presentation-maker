// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Outline PUT: writes inside the deck, never through a symlink that leads out of it. */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it } from "vitest"

type Route = typeof import("./route")

let base: string
let root: string
let outside: string
let savedRoot: string | undefined
let PUT: Route["PUT"]

const put = (id: string) => PUT(new Request(`http://localhost/api/decks/${id}/specs/outline`, {
  method: "PUT",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ content: "# new" }),
}), { params: Promise.resolve({ id }) })

beforeAll(async () => {
  base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-outline-")))
  root = path.join(base, "decks")
  outside = path.join(base, "outside")
  fs.mkdirSync(path.join(root, "ok"), { recursive: true })
  fs.mkdirSync(path.join(root, "linkdir"))
  fs.mkdirSync(path.join(root, "linkfile", "specs"), { recursive: true })
  fs.mkdirSync(outside)
  fs.writeFileSync(path.join(outside, "keep.md"), "keep")
  fs.symlinkSync(outside, path.join(root, "linkdir", "specs"))
  fs.symlinkSync(path.join(outside, "keep.md"), path.join(root, "linkfile", "specs", "outline.md"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  PUT = (await import("./route")).PUT
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(base, { recursive: true, force: true })
})

describe("PUT outline", () => {
  it("writes specs/outline.md in a normal deck", async () => {
    expect((await put("ok")).status).toBe(200)
    expect(fs.readFileSync(path.join(root, "ok", "specs", "outline.md"), "utf-8")).toBe("# new")
  })

  it("refuses a specs directory that is a symlink out of the deck", async () => {
    expect((await put("linkdir")).status).toBe(404)
    expect(fs.existsSync(path.join(outside, "outline.md"))).toBe(false)
  })

  it("does not follow an outline.md symlink out of the deck", async () => {
    expect((await put("linkfile")).status).toBe(404)
    expect(fs.readFileSync(path.join(outside, "keep.md"), "utf-8")).toBe("keep")
  })
})
