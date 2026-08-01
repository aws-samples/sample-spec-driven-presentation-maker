// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import fs from "fs"
import os from "os"
import path from "path"

import {
  SELECTION_DEFAULTS,
  readSelection,
  syncToAgentsDir,
  writeSelection,
  type SyncDirs,
} from "./agents-sync"

const ROLES = ["sdpm-spec", "sdpm-vibe", "sdpm-composer", "sdpm-single", "sdpm-style"]

let tmp: string
let dirs: SyncDirs

function writeCatalogAgent(name: string, extra: Record<string, unknown> = {}) {
  fs.writeFileSync(
    // test-controlled fixture name, not user input
    path.join(dirs.acpAgentsDir, `${name}.json`), // nosemgrep: path-join-resolve-traversal
    JSON.stringify({ name, description: `${name} agent`, tools: ["read"], ...extra }, null, 2),
  )
}

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "agents-sync-"))
  dirs = {
    acpAgentsDir: path.join(tmp, "acp-agents"),
    agentsDir: path.join(tmp, "agents"),
    configPath: path.join(tmp, ".sdpm", "acp-agent-selection.json"),
  }
  fs.mkdirSync(dirs.acpAgentsDir, { recursive: true })
  for (const r of ROLES) writeCatalogAgent(r)
})

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true })
})

describe("syncToAgentsDir", () => {
  it("derives all five roles (including style) plus the README marker", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    const files = fs.readdirSync(dirs.agentsDir).sort()
    expect(files).toEqual([...ROLES.map((r) => `${r}.json`), "README.md"].sort())
    expect(fs.readFileSync(path.join(dirs.agentsDir, "README.md"), "utf-8"))
      .toContain("do not hand-edit")
  })

  it("applies the selected model, and removes it when unset", () => {
    syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "claude-x" }, dirs)
    let agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-spec.json"), "utf-8"))
    expect(agent.model).toBe("claude-x")

    syncToAgentsDir({ ...SELECTION_DEFAULTS }, dirs)
    agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-spec.json"), "utf-8"))
    expect(agent.model).toBeUndefined()
  })

  it("re-derivation picks up catalog changes (the git-pull staleness fix)", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    // Simulate `git pull` updating the catalog
    writeCatalogAgent("sdpm-vibe", { tools: ["read", "glob"] })
    syncToAgentsDir(readSelection(dirs), dirs)
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-vibe.json"), "utf-8"))
    expect(agent.tools).toEqual(["read", "glob"])
  })

  it("overwrites hand-edits in agents/ (generated dir semantics)", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    fs.writeFileSync(path.join(dirs.agentsDir, "sdpm-spec.json"), "{\"hacked\": true}")
    syncToAgentsDir(readSelection(dirs), dirs)
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-spec.json"), "utf-8"))
    expect(agent.hacked).toBeUndefined()
    expect(agent.name).toBe("sdpm-spec")
  })

  it("writes the selected alternative under the fixed role file name", () => {
    writeCatalogAgent("my-custom-vibe")
    syncToAgentsDir({ ...SELECTION_DEFAULTS, vibe: "my-custom-vibe.json" }, dirs)
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-vibe.json"), "utf-8"))
    expect(agent.name).toBe("my-custom-vibe")
  })

  it("throws on unsafe selection names and missing catalog entries — output untouched", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    const before = fs.readdirSync(dirs.agentsDir).sort()

    expect(() => syncToAgentsDir({ ...SELECTION_DEFAULTS, vibe: "../evil.json" }, dirs))
      .toThrow(/invalid agent selection/)
    expect(() => syncToAgentsDir({ ...SELECTION_DEFAULTS, spec: "missing.json" }, dirs))
      .toThrow(/missing from catalog/)
    expect(fs.readdirSync(dirs.agentsDir).sort()).toEqual(before)
  })

  it("catalog source removed after a prior derivation: fails and keeps the old output intact", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    fs.rmSync(path.join(dirs.acpAgentsDir, "sdpm-spec.json"))
    expect(() => syncToAgentsDir(readSelection(dirs), dirs)).toThrow(/missing from catalog/)
    // The stale file is still readable (caller decides to fail the spawn),
    // and no partial new generation was written
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-spec.json"), "utf-8"))
    expect(agent.name).toBe("sdpm-spec")
  })

  it("malformed catalog JSON: throws before any write — no mixed generations", () => {
    syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "old-model" }, dirs)
    // sdpm-vibe (iterated after spec) becomes malformed; change the model so
    // a partial write would be detectable on the earlier files
    fs.writeFileSync(path.join(dirs.acpAgentsDir, "sdpm-vibe.json"), "{broken")
    expect(() => syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "new-model" }, dirs))
      .toThrow(/malformed agent definition/)
    for (const r of ROLES) {
      const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, `${r}.json`), "utf-8"))
      expect(agent.model).toBe("old-model") // all old generation, none new
    }
  })

  it("sweeps stale files that are no longer part of the derivation", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    fs.writeFileSync(path.join(dirs.agentsDir, "old-leftover.json"), "{}")
    syncToAgentsDir(readSelection(dirs), dirs)
    expect(fs.readdirSync(dirs.agentsDir)).not.toContain("old-leftover.json")
  })

  it("throws when the catalog directory is absent", () => {
    fs.rmSync(dirs.acpAgentsDir, { recursive: true })
    expect(() => syncToAgentsDir(readSelection(dirs), dirs)).toThrow(/catalog not found/)
  })

  it("swap failure (tmp -> agents rename) restores the previous generation", () => {
    syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "old-model" }, dirs)

    const realRename = fs.renameSync
    const spy = vi.spyOn(fs, "renameSync").mockImplementation((src, dest) => {
      if (String(dest) === dirs.agentsDir && String(src).includes(".tmp-")) {
        throw new Error("injected rename failure")
      }
      return realRename(src, dest)
    })
    try {
      expect(() => syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "new-model" }, dirs))
        .toThrow(/injected rename failure/)
    } finally {
      spy.mockRestore()
    }

    // Old generation fully restored — directory exists, old content, no leftovers
    const files = fs.readdirSync(dirs.agentsDir).sort()
    expect(files).toEqual([...ROLES.map((r) => `${r}.json`), "README.md"].sort())
    for (const r of ROLES) {
      const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, `${r}.json`), "utf-8"))
      expect(agent.model).toBe("old-model")
    }
    expect(fs.readdirSync(path.dirname(dirs.agentsDir)).filter((f) => f.includes(".bak-") || f.includes(".tmp-")))
      .toHaveLength(0) // backup restored, temp cleaned — no remnants
  })
})

describe("selection persistence", () => {
  it("round-trips and merges over defaults", () => {
    writeSelection({ ...SELECTION_DEFAULTS, vibe: "my-custom-vibe.json", model: "m1" }, dirs)
    const sel = readSelection(dirs)
    expect(sel.vibe).toBe("my-custom-vibe.json")
    expect(sel.spec).toBe("sdpm-spec.json")
    expect(sel.style).toBe("sdpm-style.json")
    expect(sel.model).toBe("m1")
  })
})
