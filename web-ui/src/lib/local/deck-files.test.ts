// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** A deck's chat files are read and written inside the deck, never through a symlink pointing out of it. */
import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

type DeckFiles = typeof import("./deck-files")

let base: string
let root: string
let outside: string
let savedRoot: string | undefined
let files: DeckFiles

const FILES = [".session", ".session-engine", ".session-origin.json", ".chat.json"]

beforeAll(async () => {
  base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-deck-files-")))
  root = path.join(base, "decks")
  outside = path.join(base, "outside")
  fs.mkdirSync(path.join(root, "plain"), { recursive: true })
  fs.mkdirSync(path.join(root, "linked"), { recursive: true })
  fs.mkdirSync(path.join(root, "dangling"), { recursive: true })
  fs.mkdirSync(outside)
  fs.writeFileSync(path.join(outside, "secret.json"), JSON.stringify([{ role: "user", text: "secret" }]))
  fs.writeFileSync(path.join(outside, "session"), "sess_outside")
  for (const name of FILES) {
    const target = name === ".session" ? "session" : "secret.json"
    fs.symlinkSync(path.join(outside, target), path.join(root, "linked", name))
    fs.symlinkSync(path.join(outside, `new${name}`), path.join(root, "dangling", name))
  }
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  vi.resetModules()
  files = await import("./deck-files")
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(base, { recursive: true, force: true })
})

describe("deck files", () => {
  it("round-trips in a plain deck", () => {
    expect(files.saveSessionToDeck("plain", "sess_1")).toBe(true)
    expect(files.readSessionFromDeck("plain")).toBe("sess_1")
    expect(files.saveChatToDeck("plain", [{ text: "hi" }])).toBe(true)
    expect(files.readChatFromDeck("plain")).toEqual([{ text: "hi" }])
    files.writeEngineMark("plain", { last: "v3", engines: ["v2", "v3"] })
    expect(files.readEngineMark("plain")).toEqual({ last: "v3", engines: ["v2", "v3"] })
  })

  it("does not read files that are symlinks pointing out of the deck", () => {
    expect(files.readSessionFromDeck("linked")).toBeNull()
    expect(files.readChatFromDeck("linked")).toEqual([])
    expect(files.readOriginFromDeck("linked")).toBeNull()
    expect(files.readEngineMark("linked")).toEqual({ last: "v2", engines: ["v2"] })
  })

  it("does not write through them, existing or dangling", () => {
    const before = fs.readdirSync(outside).sort()
    for (const deck of ["linked", "dangling"]) {
      expect(files.saveSessionToDeck(deck, "sess_2")).toBe(false)
      expect(files.saveChatToDeck(deck, [{ text: "overwrite" }])).toBe(false)
      files.saveOriginToDeck(deck, { kind: "kiro", sessionId: "s", title: "t" } as never)
      files.writeEngineMark(deck, { last: "v3", engines: ["v3"] })
    }
    expect(fs.readdirSync(outside).sort()).toEqual(before)
    expect(fs.readFileSync(path.join(outside, "session"), "utf-8")).toBe("sess_outside")
    expect(JSON.parse(fs.readFileSync(path.join(outside, "secret.json"), "utf-8"))).toEqual([{ role: "user", text: "secret" }])
  })
})
