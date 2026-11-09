// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A deck's own files for the outside-changes note: the walk counts slides, specs, attachments,
 * output.pptx and hand-added files, and leaves out dot names at any depth, the top-level
 * preview/, compose/ and _work/, __pycache__/ and Office lock files; it does not follow
 * symlinks; only files newer than the mark count; the walk stops at its limits with one warning.
 * The turn mark (`.session-turn`, deck-files.ts) round-trips and a broken one counts as none.
 */
import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

let deckRoot: string
let changes: typeof import("./deck-changes")
let files: typeof import("./deck-files")

const T0 = Date.UTC(2026, 10, 9, 0, 0, 0)

beforeEach(async () => {
  deckRoot = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-deck-changes-"))) // nosemgrep: path-join-resolve-traversal — constant prefix
  vi.stubEnv("SDPM_DECK_ROOT", deckRoot)
  vi.resetModules()
  changes = await import("./deck-changes")
  files = await import("./deck-files")
})

afterEach(() => {
  vi.unstubAllEnvs()
  fs.rmSync(deckRoot, { recursive: true, force: true })
})

/** Write `rel` under deck d1 with mtime `at` (ms). */
function put(rel: string, at: number): string {
  const file = path.join(deckRoot, "d1", rel) // nosemgrep: path-join-resolve-traversal — constant names in a tmpdir
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, "x")
  fs.utimesSync(file, at / 1000, at / 1000)
  return file
}

const deck = () => path.join(deckRoot, "d1") // nosemgrep: path-join-resolve-traversal — constant deck id in a tmpdir

describe("changedDeckFiles", () => {
  it("lists the deck's own files changed after the mark, sorted, and leaves out the Web UI's, previews and caches", () => {
    const later = T0 + 2000
    for (const rel of [
      "deck.json", "slides/intro.json", "specs/outline.md", "attachments/a.pdf", "output.pptx", "notes-by-hand.txt",
      ".session", ".chat.json", ".session-turn", ".DS_Store", "slides/.intro.json.tmp", ".cache/x.json",
      "preview/intro.png", "compose/s1.json", "_work/m.json", "includes/__pycache__/m.pyc", "~$output.pptx",
      "slides/preview/kept.json",
    ]) put(rel, later)
    put("slides/old.json", T0)
    expect(changes.changedDeckFiles(deck(), T0)).toEqual({
      files: ["attachments/a.pdf", "deck.json", "notes-by-hand.txt", "output.pptx", "slides/intro.json", "slides/preview/kept.json", "specs/outline.md"],
      more: 0,
    })
  })

  it("counts only files strictly newer than the mark", () => {
    put("slides/same.json", T0)
    put("slides/newer.json", T0 + 1000)
    expect(changes.changedDeckFiles(deck(), T0).files).toEqual(["slides/newer.json"])
    expect(changes.newestDeckFileMtime(deck())).toBe(T0 + 1000)
  })

  it("does not follow symlinks", () => {
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-deck-outside-")) // nosemgrep: path-join-resolve-traversal — constant prefix
    try {
      fs.writeFileSync(path.join(outside, "secret.json"), "x") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
      put("slides/a.json", T0 + 1000)
      fs.symlinkSync(outside, path.join(deck(), "linked")) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
      fs.symlinkSync(path.join(outside, "secret.json"), path.join(deck(), "slides", "link.json")) // nosemgrep: path-join-resolve-traversal — constant names in tmpdirs
      expect(changes.changedDeckFiles(deck(), 0).files).toEqual(["slides/a.json"])
    } finally {
      fs.rmSync(outside, { recursive: true, force: true })
    }
  })

  it("lists the first 20 and counts the rest", () => {
    for (let i = 0; i < 23; i++) put(`slides/s${String(i).padStart(2, "0")}.json`, T0 + 1000)
    const { files: listed, more } = changes.changedDeckFiles(deck(), T0)
    expect(listed).toHaveLength(20)
    expect(listed[0]).toBe("slides/s00.json")
    expect(listed.at(-1)).toBe("slides/s19.json")
    expect(more).toBe(3)
  })

  it("gives nothing for a deck directory that is gone, with one warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const gone = path.join(deckRoot, "gone") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
      expect(changes.changedDeckFiles(gone, 0)).toEqual({ files: [], more: 0 })
      expect(changes.newestDeckFileMtime(gone)).toBe(0)
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })

  it("stops past the depth limit, with one warning, and uses what it found", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const levels = Array.from({ length: changes.MAX_DEPTH }, (_, i) => `l${i + 1}`)
      put(`${levels.slice(0, changes.MAX_DEPTH - 1).join("/")}/deep.json`, T0 + 1000)
      put(`${levels.join("/")}/too-deep.json`, T0 + 1000)
      expect(changes.changedDeckFiles(deck(), T0).files).toEqual([`${levels.slice(0, changes.MAX_DEPTH - 1).join("/")}/deep.json`])
      changes.changedDeckFiles(deck(), T0)
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })

  it("stops past the entry limit, with one warning, and uses what it found", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const dir = path.join(deck(), "attachments") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
      fs.mkdirSync(dir, { recursive: true })
      for (let i = 0; i <= changes.MAX_ENTRIES; i++) fs.writeFileSync(path.join(dir, `f${i}`), "") // nosemgrep: path-join-resolve-traversal — generated names in a tmpdir
      const { files: listed, more } = changes.changedDeckFiles(deck(), 0)
      expect(listed.length + more).toBe(changes.MAX_ENTRIES - 1)
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })
})

describe("turn mark", () => {
  it("round-trips, and is written through a temp file", () => {
    fs.mkdirSync(deck())
    files.writeTurnMark("d1", { sessionId: "sess_1", endedAt: T0 })
    expect(files.readTurnMark("d1")).toEqual({ sessionId: "sess_1", endedAt: T0 })
    expect(fs.readdirSync(deck())).toEqual([".session-turn"])
    expect(JSON.parse(fs.readFileSync(path.join(deck(), ".session-turn"), "utf-8"))).toEqual({ version: 1, sessionId: "sess_1", endedAt: T0 }) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
  })

  it("is none for a deck without one, and for a broken one with one warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      fs.mkdirSync(deck())
      expect(files.readTurnMark("d1")).toBeNull()
      const mark = path.join(deck(), ".session-turn") // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
      for (const text of ["{", JSON.stringify({ version: 2, sessionId: "s", endedAt: T0 }), JSON.stringify({ version: 1, sessionId: "../x", endedAt: T0 }), JSON.stringify({ version: 1, sessionId: "s", endedAt: -1 })]) {
        fs.writeFileSync(mark, text)
        expect(files.readTurnMark("d1")).toBeNull()
      }
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })

  it("logs a mark it cannot write and leaves no temp file", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      fs.mkdirSync(path.join(deck(), ".session-turn"), { recursive: true }) // nosemgrep: path-join-resolve-traversal — constant name in a tmpdir
      files.writeTurnMark("d1", { sessionId: "sess_1", endedAt: T0 })
      expect(warn.mock.calls.some((call) => String(call[0]).includes("could not write"))).toBe(true)
      expect(fs.readdirSync(deck())).toEqual([".session-turn"])
    } finally {
      warn.mockRestore()
    }
  })
})
