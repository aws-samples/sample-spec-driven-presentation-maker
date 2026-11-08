// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * acp-models.json: no file is an empty list; an engine's list is written next to the other's and
 * read back; a broken file, another version or entries without id and name are dropped with a
 * warning; a write that fails is logged and throws nothing.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

let dir: string
let cache: typeof import("./model-cache")
let warn: ReturnType<typeof vi.spyOn>

const file = () => path.resolve(dir, "acp-models.json")

const HAIKU = { modelId: "claude-haiku-5.5", name: "Claude Haiku 5.5", effortLevels: ["low", "medium"], defaultEffort: "medium", rate: 0.06 }

beforeEach(async () => {
  dir = fs.mkdtempSync(path.resolve(os.tmpdir(), "sdpm-acp-models-"))
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", dir)
  warn = vi.spyOn(console, "warn").mockImplementation(() => {})
  vi.resetModules()
  cache = await import("./model-cache")
})

afterEach(() => {
  warn.mockRestore()
  vi.unstubAllEnvs()
  fs.rmSync(dir, { recursive: true, force: true })
})

describe("model cache", () => {
  it("is empty without a file, silently", () => {
    expect(cache.readModelCache("v3")).toEqual([])
    expect(warn).not.toHaveBeenCalled()
  })

  it("keeps each engine's list", () => {
    cache.writeModelCache("v3", [HAIKU, { modelId: "auto", name: "Auto", rate: 1 }])
    cache.writeModelCache("v2", [{ modelId: "auto", name: "auto" }])
    expect(cache.readModelCache("v3")).toEqual([HAIKU, { modelId: "auto", name: "Auto", rate: 1 }])
    expect(cache.readModelCache("v2")).toEqual([{ modelId: "auto", name: "auto" }])
    expect(JSON.parse(fs.readFileSync(file(), "utf-8")).version).toBe(1)
    expect(fs.readdirSync(dir)).toEqual(["acp-models.json"])
  })

  it.each([
    ["broken JSON", "{"],
    ["another version", JSON.stringify({ version: 2, engines: { v3: [HAIKU] } })],
    ["a list that is not one", JSON.stringify({ version: 1, engines: { v3: "auto" } })],
  ])("ignores %s with a warning", (_case, text) => {
    fs.writeFileSync(file(), text)
    expect(cache.readModelCache("v3")).toEqual([])
    expect(warn).toHaveBeenCalledOnce()
  })

  it("drops entries without a string id and name, and fields of the wrong type", () => {
    fs.writeFileSync(file(), JSON.stringify({ version: 1, engines: { v3: [
      { modelId: "auto", name: "Auto", rate: "1", effortLevels: [] }, { modelId: 3, name: "x" }, { name: "no id" }, null,
    ] } }))
    expect(cache.readModelCache("v3")).toEqual([{ modelId: "auto", name: "Auto" }])
    expect(warn).toHaveBeenCalledOnce()
  })

  it("logs a write that fails and throws nothing", () => {
    fs.rmSync(dir, { recursive: true })
    fs.writeFileSync(dir, "a file where the directory should be")
    try {
      expect(() => cache.writeModelCache("v3", [HAIKU])).not.toThrow()
      expect(warn).toHaveBeenCalledWith("[acp-models] could not write %s: %s", expect.any(String), expect.any(String))
    } finally {
      fs.rmSync(dir, { force: true })
      fs.mkdirSync(dir)
    }
  })
})
