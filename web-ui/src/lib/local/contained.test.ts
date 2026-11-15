// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** resolveWithin: lexical and symlink-resolved containment with a separator boundary. */
import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it } from "vitest"

import { mkdirWithin, resolveWithin } from "./contained"

let base: string
let root: string
let sibling: string

beforeAll(() => {
  base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-contained-")))
  root = path.join(base, "data")
  sibling = path.join(base, "data-evil")
  fs.mkdirSync(path.join(root, "sub"), { recursive: true })
  fs.mkdirSync(sibling)
  fs.writeFileSync(path.join(root, "sub", "a.txt"), "a")
  fs.writeFileSync(path.join(sibling, "b.txt"), "b")
  fs.symlinkSync(path.join(sibling, "b.txt"), path.join(root, "out.txt"))
  fs.symlinkSync(sibling, path.join(root, "outdir"))
  fs.symlinkSync(path.join(root, "sub", "a.txt"), path.join(root, "in.txt"))
})

afterAll(() => {
  fs.rmSync(base, { recursive: true, force: true })
})

describe("resolveWithin", () => {
  it("returns a regular file under the root", () => {
    expect(resolveWithin(root, "sub", "a.txt")).toBe(path.join(root, "sub", "a.txt"))
  })

  it("returns the real path of a symlink that stays inside", () => {
    expect(resolveWithin(root, "in.txt")).toBe(path.join(root, "sub", "a.txt"))
  })

  it("refuses symlinks pointing outside the root", () => {
    expect(resolveWithin(root, "out.txt")).toBeNull()
    expect(resolveWithin(root, "outdir", "b.txt")).toBeNull()
  })

  it("refuses `..` and a sibling whose name starts with the root's", () => {
    expect(resolveWithin(root, "..", "data-evil", "b.txt")).toBeNull()
    expect(resolveWithin(root, "../data-evil/b.txt")).toBeNull()
  })

  it("returns the lexical path of a missing file and null for a missing root", () => {
    expect(resolveWithin(root, "sub", "missing.txt")).toBe(path.join(root, "sub", "missing.txt"))
    expect(resolveWithin(root, "sub", "new", "deeper.txt")).toBe(path.join(root, "sub", "new", "deeper.txt"))
    expect(resolveWithin(path.join(base, "nope"), "x")).toBeNull()
  })

  it("refuses a missing file whose directory is a symlink pointing outside", () => {
    // A write would create <sibling>/new.txt.
    expect(resolveWithin(root, "outdir", "new.txt")).toBeNull()
    expect(resolveWithin(root, "outdir", "new", "deeper.txt")).toBeNull()
  })

  it("refuses a dangling symlink", () => {
    fs.symlinkSync(path.join(sibling, "not-yet.txt"), path.join(root, "dangling.txt"))
    expect(resolveWithin(root, "dangling.txt")).toBeNull()
    expect(fs.existsSync(path.join(sibling, "not-yet.txt"))).toBe(false)
  })

  it("resolves a root given through a symlink", () => {
    const alias = path.join(base, "alias")
    fs.symlinkSync(root, alias)
    expect(resolveWithin(alias, "sub", "a.txt")).toBe(path.join(root, "sub", "a.txt"))
  })
})

describe("mkdirWithin", () => {
  it("creates a missing directory under the root and returns its real path", () => {
    expect(mkdirWithin(root, ["made", "deeper"])).toBe(path.join(root, "made", "deeper"))
    expect(fs.statSync(path.join(root, "made", "deeper")).isDirectory()).toBe(true)
  })

  it("refuses a symlinked directory pointing outside and creates nothing there", () => {
    expect(mkdirWithin(root, ["outdir", "made"])).toBeNull()
    expect(fs.existsSync(path.join(sibling, "made"))).toBe(false)
    expect(mkdirWithin(root, ["outdir"])).toBeNull()
  })
})
