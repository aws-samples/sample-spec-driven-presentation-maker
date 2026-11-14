// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** User style save: a target that is a symlink leading out of the styles directory is refused. */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

let base: string
let dir: string
let outside: string

vi.mock("@/lib/local/sdpmPaths", () => ({ getUserStylesDir: () => dir }))

const post = async (name: string) => {
  const { POST } = await import("./route")
  return POST(new Request("http://localhost/api/styles/user", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, html: "<p>x</p>" }),
  }))
}

beforeAll(() => {
  base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-style-")))
  dir = path.join(base, "styles")
  outside = path.join(base, "outside")
  fs.mkdirSync(dir)
  fs.mkdirSync(outside)
  fs.writeFileSync(path.join(outside, "keep.html"), "keep")
  fs.symlinkSync(path.join(outside, "keep.html"), path.join(dir, "linked.html"))
  fs.symlinkSync(path.join(outside, "new.html"), path.join(dir, "dangling.html"))
})

afterAll(() => {
  fs.rmSync(base, { recursive: true, force: true })
})

describe("POST /api/styles/user", () => {
  it("saves a normal style", async () => {
    expect((await post("plain")).status).toBe(200)
    expect(fs.readFileSync(path.join(dir, "plain.html"), "utf-8")).toBe("<p>x</p>")
  })

  it("does not write through symlinks leading out of the directory", async () => {
    expect((await post("linked")).status).toBe(400)
    expect((await post("dangling")).status).toBe(400)
    expect(fs.readFileSync(path.join(outside, "keep.html"), "utf-8")).toBe("keep")
    expect(fs.existsSync(path.join(outside, "new.html"))).toBe(false)
  })
})
