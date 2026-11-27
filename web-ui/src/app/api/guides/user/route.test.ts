// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The local guide routes: the name rule, the symlink containment the style route has, and
 * delete / rename. A guide name admits anything a single path component can hold except a
 * dot, so a Japanese name works and `acme.v2` does not — it is also a payload key.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

let base: string
let dir: string
let outside: string

vi.mock("@/lib/local/sdpmPaths", () => ({ getUserGuidesDir: () => dir }))

const GUIDE = "---\ndescription: Mine.\ntags: [composer]\n---\n\nMy rules.\n"

const post = async (name: string, text = GUIDE) => {
  const { POST } = await import("./route")
  return POST(new Request("http://localhost/api/guides/user", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, text }),
  }))
}

const del = async (name: string) => {
  const { DELETE } = await import("./[name]/route")
  return DELETE(new Request("http://localhost", { method: "DELETE" }), { params: Promise.resolve({ name }) })
}

const patch = async (name: string, newName: string) => {
  const { PATCH } = await import("./[name]/route")
  return PATCH(
    new Request("http://localhost", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ newName }),
    }),
    { params: Promise.resolve({ name }) },
  )
}

beforeAll(() => {
  base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-guide-")))
  dir = path.join(base, "guides")
  outside = path.join(base, "outside")
  fs.mkdirSync(dir)
  fs.mkdirSync(outside)
  fs.writeFileSync(path.join(outside, "keep.md"), "keep")
  fs.symlinkSync(path.join(outside, "keep.md"), path.join(dir, "linked.md"))
  fs.symlinkSync(path.join(outside, "new.md"), path.join(dir, "dangling.md"))
})

afterAll(() => {
  fs.rmSync(base, { recursive: true, force: true })
})

beforeEach(() => {
  for (const name of ["plain.md", "社内標準.md", "ours.md"]) {
    fs.rmSync(path.join(dir, name), { force: true })
  }
})

describe("POST /api/guides/user", () => {
  it("saves a guide as markdown", async () => {
    expect((await post("plain")).status).toBe(200)
    expect(fs.readFileSync(path.join(dir, "plain.md"), "utf-8")).toBe(GUIDE)
  })

  it("accepts a name a style route's regex would refuse", async () => {
    expect((await post("社内標準")).status).toBe(200)
    expect(fs.existsSync(path.join(dir, "社内標準.md"))).toBe(true)
  })

  it.each(["acme.v2", "sub/x", "..", ""])("refuses %j", async (name) => {
    expect((await post(name)).status).toBe(400)
  })

  it("refuses an empty body", async () => {
    expect((await post("plain", "")).status).toBe(400)
    expect(fs.existsSync(path.join(dir, "plain.md"))).toBe(false)
  })

  it("does not write through symlinks leading out of the directory", async () => {
    expect((await post("linked")).status).toBe(400)
    expect((await post("dangling")).status).toBe(400)
    expect(fs.readFileSync(path.join(outside, "keep.md"), "utf-8")).toBe("keep")
    expect(fs.existsSync(path.join(outside, "new.md"))).toBe(false)
  })
})

describe("DELETE /api/guides/user/[name]", () => {
  it("removes the file", async () => {
    await post("plain")
    expect((await del("plain")).status).toBe(200)
    expect(fs.existsSync(path.join(dir, "plain.md"))).toBe(false)
  })

  it("404s a guide that is not there", async () => {
    expect((await del("no-such-guide")).status).toBe(404)
  })

  it("400s a bad name", async () => {
    expect((await del("acme.v2")).status).toBe(400)
  })
})

describe("PATCH /api/guides/user/[name]", () => {
  it("renames the file", async () => {
    await post("plain")
    const res = await patch("plain", "ours")
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ renamed: { from: "plain", to: "ours" } })
    expect(fs.existsSync(path.join(dir, "ours.md"))).toBe(true)
    expect(fs.existsSync(path.join(dir, "plain.md"))).toBe(false)
  })

  it("404s a source that is not there", async () => {
    expect((await patch("no-such-guide", "ours")).status).toBe(404)
  })

  it("409s a destination that already exists", async () => {
    await post("plain")
    await post("ours")
    expect((await patch("plain", "ours")).status).toBe(409)
    expect(fs.existsSync(path.join(dir, "plain.md"))).toBe(true)
  })

  it.each(["acme.v2", "sub/x", ""])("400s the new name %j", async (newName) => {
    await post("plain")
    expect((await patch("plain", newName)).status).toBe(400)
  })
})
