// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { afterEach, beforeEach, describe, expect, it } from "vitest"
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
    path.join(dirs.acpAgentsDir, `${name}.json`),
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

  it("rejects unsafe file names and skips missing catalog entries", () => {
    syncToAgentsDir({ ...SELECTION_DEFAULTS, vibe: "../evil.json", spec: "missing.json" }, dirs)
    const files = fs.readdirSync(dirs.agentsDir)
    expect(files).not.toContain("sdpm-vibe.json")
    expect(files).not.toContain("sdpm-spec.json")
    expect(files).toContain("sdpm-composer.json")
  })

  it("is a no-op when the catalog directory is absent", () => {
    fs.rmSync(dirs.acpAgentsDir, { recursive: true })
    syncToAgentsDir(readSelection(dirs), dirs)
    expect(fs.existsSync(dirs.agentsDir)).toBe(false)
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
