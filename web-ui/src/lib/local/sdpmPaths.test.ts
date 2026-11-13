// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Guard against directory renames breaking the local-mode path anchors.
 *
 * These anchors point outside web-ui/ into the repo's sdpm/ distribution.
 * Cloud builds exclude the API routes and other tests mock the API, so a
 * stale path here ships silently — this test resolves the real filesystem.
 * (vitest runs with cwd = web-ui/, same as `next dev`.)
 *
 * Also holds the deck-root order table (resolveDeckRoot), mirrored in tests/test_deck_root.py.
 */
import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { resolveDeckRoot } from "./deck-paths"
import { BUNDLED_STYLES_DIR, BUNDLED_TEMPLATES_DIR, SDPM_ROOT, getBuiltinTemplateNotes, setBuiltinTemplateNote } from "./sdpmPaths"

describe("sdpm path anchors", () => {
  it("SDPM_ROOT points at the skill distribution", () => {
    expect(fs.existsSync(path.join(SDPM_ROOT, "SKILL.md"))).toBe(true)
  })

  it("bundled templates dir exists and contains .pptx templates", () => {
    expect(fs.existsSync(BUNDLED_TEMPLATES_DIR)).toBe(true)
    const pptx = fs.readdirSync(BUNDLED_TEMPLATES_DIR).filter((f) => f.endsWith(".pptx"))
    expect(pptx.length).toBeGreaterThan(0)
  })

  it("bundled styles dir exists", () => {
    expect(fs.existsSync(BUNDLED_STYLES_DIR)).toBe(true)
  })
})

// (SDPM_DECK_ROOT, SDPM_OUTPUT_DIR, config.json content, expected); "<tmp>" is the test's tmp dir.
// tests/test_deck_root.py holds the same table for the CLI and both local MCP servers.
const DECK_ROOT_TABLE: Array<[string | undefined, string | undefined, object | string | undefined, string]> = [
  [undefined, undefined, undefined, "~/Documents/SDPM-Presentations"],
  [undefined, undefined, { output_dir: "<tmp>/cfg" }, "<tmp>/cfg"],
  [undefined, undefined, { output_dir: "~/cfg-decks" }, "~/cfg-decks"],
  [undefined, undefined, { output_dir: "~" }, "~"],
  [undefined, undefined, { output_dir: "" }, "~/Documents/SDPM-Presentations"],
  [undefined, undefined, { extra_sources: [] }, "~/Documents/SDPM-Presentations"],
  // Python on WSL uses the Windows Documents folder here; the Web UI keeps the default.
  [undefined, undefined, "{not json", "~/Documents/SDPM-Presentations"],
  [undefined, "<tmp>/out", { output_dir: "<tmp>/cfg" }, "<tmp>/out"],
  ["<tmp>/deck", "<tmp>/out", { output_dir: "<tmp>/cfg" }, "<tmp>/deck"],
  ["", "<tmp>/out", undefined, "<tmp>/out"],
]

describe("deck root order", () => {
  let tmp: string

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-deck-root-")) // nosemgrep: path-join-resolve-traversal — constant prefix
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    fs.rmSync(tmp, { recursive: true, force: true })
  })

  it.each(DECK_ROOT_TABLE)("SDPM_DECK_ROOT=%j SDPM_OUTPUT_DIR=%j config=%j → %s", (deckRoot, outputDir, config, expected) => {
    const value = (text: string) => text.replaceAll("<tmp>", tmp)
    const expand = (text: string) => value(text).replace(/^~(?=\/|$)/, os.homedir())
    vi.stubEnv("SDPM_DECK_ROOT", deckRoot === undefined ? undefined : value(deckRoot))
    vi.stubEnv("SDPM_OUTPUT_DIR", outputDir === undefined ? undefined : value(outputDir))
    vi.stubEnv("XDG_CONFIG_HOME", path.join(tmp, "xdg"))
    vi.stubEnv("APPDATA", path.join(tmp, "xdg"))
    const configDir = path.join(tmp, "xdg", "sdpm")
    fs.mkdirSync(configDir, { recursive: true })
    if (config !== undefined) {
      const text = typeof config === "string" ? config : value(JSON.stringify(config))
      fs.writeFileSync(path.join(configDir, "config.json"), text)
    }
    expect(path.resolve(resolveDeckRoot())).toBe(path.resolve(expand(expected))) // nosemgrep: path-join-resolve-traversal — constant table rows in a tmpdir
  })
})

// Mirrors tests/test_templates_resolution.py::test_builtin_notes_migrate_from_legacy_cache.
describe("builtin template notes", () => {
  let tmp: string
  let statePath: string

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-notes-")) // nosemgrep: path-join-resolve-traversal — constant prefix
    vi.stubEnv("XDG_CONFIG_HOME", tmp)
    vi.stubEnv("APPDATA", tmp)
    fs.mkdirSync(path.join(tmp, "sdpm"))
    statePath = path.join(tmp, "sdpm", "state.json")
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    fs.rmSync(tmp, { recursive: true, force: true })
  })

  it("moves legacy notes out of the analysis cache once (a legacy note is the newer edit)", () => {
    fs.writeFileSync(statePath, JSON.stringify({
      pinned_styles: ["report"],
      builtin_template_notes: { edited: "Moved note", kept: "Kept note" },
      template_metadata: {
        "builtin:blank-dark": { description: " Old note ", layout_count: 7 },
        "builtin:edited": { description: "Edited by an older install" },
        "builtin:empty": { description: "" },
        "my-brand": { description: "User template note" },
      },
    }))

    expect(getBuiltinTemplateNotes()).toEqual({ edited: "Edited by an older install", kept: "Kept note", "blank-dark": "Old note" })
    const state = JSON.parse(fs.readFileSync(statePath, "utf-8"))
    expect(state.template_metadata).toEqual({
      "builtin:blank-dark": { layout_count: 7 },
      "builtin:edited": {},
      "builtin:empty": {},
      "my-brand": { description: "User template note" },
    })
    expect(state.pinned_styles).toEqual(["report"])
    expect(fs.readdirSync(path.dirname(statePath))).toEqual(["state.json"]) // no temp file left behind
    expect(getBuiltinTemplateNotes()).toEqual({ edited: "Edited by an older install", kept: "Kept note", "blank-dark": "Old note" })
  })

  it("sets and clears a note without touching the cache", () => {
    fs.writeFileSync(statePath, JSON.stringify({ template_metadata: { "builtin:a": { layout_count: 3 } } }))
    setBuiltinTemplateNote("a", "Use for reports")
    expect(getBuiltinTemplateNotes()).toEqual({ a: "Use for reports" })
    setBuiltinTemplateNote("a", "")
    const state = JSON.parse(fs.readFileSync(statePath, "utf-8"))
    expect(state.builtin_template_notes).toEqual({})
    expect(state.template_metadata).toEqual({ "builtin:a": { layout_count: 3 } })
  })

  it("returns the notes when state.json cannot be rewritten", () => {
    const original = JSON.stringify({ template_metadata: { "builtin:a": { description: "Old note" } } })
    fs.writeFileSync(statePath, original)
    const rename = vi.spyOn(fs, "renameSync").mockImplementation(() => {
      throw Object.assign(new Error("read-only"), { code: "EACCES" })
    })
    try {
      expect(getBuiltinTemplateNotes()).toEqual({ a: "Old note" })
    } finally {
      rename.mockRestore()
    }
    expect(fs.readFileSync(statePath, "utf-8")).toBe(original)
    expect(fs.readdirSync(path.dirname(statePath))).toEqual(["state.json"])
  })
})
