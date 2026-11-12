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
  withAsyncCompose,
  withPermissions,
  writeSelection,
  type SyncDirs,
} from "./agents-sync"

const ROLES = ["sdpm-orchestrator", "sdpm-composer", "sdpm-style", "sdpm-translate"]

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
  it("derives all four roles plus the README marker, as README.txt (V3 reads every .md here as an agent)", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    const files = fs.readdirSync(dirs.agentsDir).sort()
    expect(files).toEqual([...ROLES.map((r) => `${r}.json`), "README.txt"].sort())
    expect(fs.readFileSync(path.join(dirs.agentsDir, "README.txt"), "utf-8"))
      .toContain("do not hand-edit")
  })

  it("replaces an old README.md marker", () => {
    fs.mkdirSync(dirs.agentsDir, { recursive: true })
    fs.writeFileSync(path.join(dirs.agentsDir, "README.md"), "old marker")
    syncToAgentsDir(readSelection(dirs), dirs)
    expect(fs.readdirSync(dirs.agentsDir)).not.toContain("README.md")
  })

  it("applies the selected model, and removes it when unset", () => {
    syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "claude-x" }, dirs)
    let agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8"))
    expect(agent.model).toBe("claude-x")

    syncToAgentsDir({ ...SELECTION_DEFAULTS }, dirs)
    agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8"))
    expect(agent.model).toBeUndefined()
  })

  it("writes the Settings model into every definition, the composer's included", () => {
    const read = (file: string) => JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, file), "utf-8")) // nosemgrep: path-join-resolve-traversal — constant definition names in a tmpdir
    writeCatalogAgent("sdpm-composer", { model: "catalog-model" })
    syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "claude-x" }, dirs)
    for (const file of ["sdpm-composer.json", "sdpm-orchestrator.json", "sdpm-style.json", "sdpm-translate.json"]) expect(read(file).model).toBe("claude-x")
    syncToAgentsDir({ ...SELECTION_DEFAULTS }, dirs)
    expect(read("sdpm-composer.json").model).toBeUndefined()
  })

  it("re-derivation picks up catalog changes (the git-pull staleness fix)", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    // Simulate `git pull` updating the catalog
    writeCatalogAgent("sdpm-translate", { tools: ["read", "glob"] })
    syncToAgentsDir(readSelection(dirs), dirs)
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-translate.json"), "utf-8"))
    expect(agent.tools).toEqual(["read", "glob"])
  })

  it("overwrites hand-edits in agents/ (generated dir semantics)", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    fs.writeFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "{\"hacked\": true}")
    syncToAgentsDir(readSelection(dirs), dirs)
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8"))
    expect(agent.hacked).toBeUndefined()
    expect(agent.name).toBe("sdpm-orchestrator")
  })

  it("writes the selected alternative under the fixed role file name", () => {
    writeCatalogAgent("my-custom-translate")
    syncToAgentsDir({ ...SELECTION_DEFAULTS, translate: "my-custom-translate.json" }, dirs)
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-translate.json"), "utf-8"))
    expect(agent.name).toBe("my-custom-translate")
  })

  it("throws on unsafe selection names and missing catalog entries — output untouched", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    const before = fs.readdirSync(dirs.agentsDir).sort()

    expect(() => syncToAgentsDir({ ...SELECTION_DEFAULTS, translate: "../evil.json" }, dirs))
      .toThrow(/invalid agent selection/)
    expect(() => syncToAgentsDir({ ...SELECTION_DEFAULTS, orchestrator: "missing.json" }, dirs))
      .toThrow(/missing from catalog/)
    expect(fs.readdirSync(dirs.agentsDir).sort()).toEqual(before)
  })

  it("catalog source removed after a prior derivation: fails and keeps the old output intact", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    fs.rmSync(path.join(dirs.acpAgentsDir, "sdpm-orchestrator.json"))
    expect(() => syncToAgentsDir(readSelection(dirs), dirs)).toThrow(/missing from catalog/)
    // The stale file is still readable (caller decides to fail the spawn),
    // and no partial new generation was written
    const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8"))
    expect(agent.name).toBe("sdpm-orchestrator")
  })

  it("malformed catalog JSON: throws before any write — no mixed generations", () => {
    syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "old-model" }, dirs)
    // sdpm-translate (iterated after orchestrator) becomes malformed; change the model so
    // a partial write would be detectable on the earlier files
    fs.writeFileSync(path.join(dirs.acpAgentsDir, "sdpm-translate.json"), "{broken")
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
    expect(files).toEqual([...ROLES.map((r) => `${r}.json`), "README.txt"].sort())
    for (const r of ROLES) {
      const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, `${r}.json`), "utf-8"))
      expect(agent.model).toBe("old-model")
    }
    expect(fs.readdirSync(path.dirname(dirs.agentsDir)).filter((f) => f.includes(".bak-") || f.includes(".tmp-")))
      .toHaveLength(0) // backup restored, temp cleaned — no remnants
  })
})

describe("syncToAgentsDir digest", () => {
  const leftovers = () => fs.readdirSync(path.dirname(dirs.agentsDir)).filter((f) => f.includes(".bak-") || f.includes(".tmp-"))

  it("returns the same digest for the same input", () => {
    const first = syncToAgentsDir(readSelection(dirs), dirs)
    expect(first).toMatch(/^[0-9a-f]{64}$/)
    fs.rmSync(dirs.agentsDir, { recursive: true })
    expect(syncToAgentsDir(readSelection(dirs), dirs)).toBe(first)
  })

  it("leaves agents/ as it is when nothing changed: same inode, no temp or backup directory", () => {
    const first = syncToAgentsDir(readSelection(dirs), dirs)
    const inode = fs.statSync(dirs.agentsDir).ino
    const realMkdir = fs.mkdirSync
    const made: string[] = []
    const spy = vi.spyOn(fs, "mkdirSync").mockImplementation((dir, opts) => { made.push(String(dir)); return realMkdir(dir, opts) })
    try {
      expect(syncToAgentsDir(readSelection(dirs), dirs)).toBe(first)
    } finally {
      spy.mockRestore()
    }
    expect(fs.statSync(dirs.agentsDir).ino).toBe(inode)
    expect(made.filter((dir) => dir.includes(".tmp-") || dir.includes(".bak-"))).toEqual([])
    expect(leftovers()).toEqual([])
  })

  it("swaps and returns another digest when the selection changed", () => {
    const first = syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "old-model" }, dirs)
    const inode = fs.statSync(dirs.agentsDir).ino
    const second = syncToAgentsDir({ ...SELECTION_DEFAULTS, model: "new-model" }, dirs)
    expect(second).not.toBe(first)
    expect(fs.statSync(dirs.agentsDir).ino).not.toBe(inode)
    expect(JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8")).model).toBe("new-model")
  })

  it.skipIf(process.platform === "win32" || process.getuid?.() === 0)("still swaps when a file in agents/ cannot be read", () => {
    const first = syncToAgentsDir(readSelection(dirs), dirs)
    const unreadable = path.join(dirs.agentsDir, "sdpm-style.json")
    fs.chmodSync(unreadable, 0o000)
    const inode = fs.statSync(dirs.agentsDir).ino
    try {
      expect(syncToAgentsDir(readSelection(dirs), dirs)).toBe(first)
    } finally {
      if (fs.existsSync(unreadable)) fs.chmodSync(unreadable, 0o644)
    }
    expect(fs.statSync(dirs.agentsDir).ino).not.toBe(inode)
    expect(fs.readFileSync(unreadable, "utf-8")).toContain("sdpm-style")
  })
})

/** The orchestrator entry of the catalog, in V2's form. */
const ORCHESTRATOR_V2 = {
  name: "sdpm-orchestrator",
  tools: ["@sdpm/list_styles", "@sdpm/start_presentation", "use_subagent", "read", "glob", "grep", "web_search", "web_fetch"],
  allowedTools: ["@sdpm/list_styles", "@sdpm/start_presentation", "use_subagent", "read", "glob", "grep", "web_search", "web_fetch"],
  toolsSettings: { subagent: { availableAgents: ["sdpm-composer"], trustedAgents: ["sdpm-composer"] } },
  mcpServers: { sdpm: { command: "uv", args: ["run", "python", "server_acp.py"], timeout: 120000 } },
  prompt: "file://../acp-agents/prompts/orchestrator.md",
  welcomeMessage: "Drop material",
  resources: [],
}

describe("withPermissions (definitions both engines read)", () => {
  it("keeps the V2 fields, adds subagent/<name> to tools and derives permissions.rules from allowedTools", () => {
    const converted = withPermissions(ORCHESTRATOR_V2, "sdpm-orchestrator.json")
    const { tools, permissions, ...rest } = converted
    expect({ ...rest, tools: ORCHESTRATOR_V2.tools }).toEqual(ORCHESTRATOR_V2)
    expect(tools).toEqual([...ORCHESTRATOR_V2.tools, "subagent/sdpm-composer"])
    expect(permissions).toEqual({ rules: [
      { capability: "mcp", match: ["sdpm/list_styles", "sdpm/start_presentation"], effect: "allow" },
      { capability: "fs_read", effect: "allow" },
      { capability: "web_search", effect: "allow" },
      { capability: "web_fetch", effect: "allow" },
      { capability: "subagent", match: ["sdpm-composer"], effect: "allow" },
    ] })
    expect(ORCHESTRATOR_V2.tools).not.toContain("subagent/sdpm-composer")
  })

  it("does not add a subagent tool twice and makes no rule for an agent without allowed tools", () => {
    const converted = withPermissions({ name: "a", tools: ["subagent/x"], toolsSettings: { subagent: { availableAgents: ["x"] } } }, "a.json")
    expect(converted.tools).toEqual(["subagent/x"])
    expect(converted.permissions).toEqual({ rules: [] })
  })

  it("uses an entry that already has permissions as it is", () => {
    const v3 = { name: "a", tools: ["read"], permissions: { rules: [{ capability: "fs_read", effect: "ask" }] } }
    expect(withPermissions(v3, "a.json")).toBe(v3)
  })

  it("makes no rule for an allowed tool V3 has no capability for, with one warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const agent = { name: "a", allowedTools: ["read", "shell"] }
      expect(withPermissions(agent, "unknown-tool.json").permissions).toEqual({ rules: [{ capability: "fs_read", effect: "allow" }] })
      withPermissions(agent, "unknown-tool.json")
      expect(warn).toHaveBeenCalledOnce()
      expect(String(warn.mock.calls[0][2])).toBe("shell")
    } finally {
      warn.mockRestore()
    }
  })

  it("ignores a field that is not a list of names, with a warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const converted = withPermissions({ name: "a", tools: "read", allowedTools: ["read"] }, "bad.json")
      expect(converted.tools).toBe("read")
      expect(converted.permissions).toEqual({ rules: [{ capability: "fs_read", effect: "allow" }] })
      expect(warn).toHaveBeenCalledOnce()
    } finally {
      warn.mockRestore()
    }
  })

  it("is applied to every generated definition", () => {
    writeCatalogAgent("sdpm-orchestrator", ORCHESTRATOR_V2)
    syncToAgentsDir(readSelection(dirs), dirs)
    for (const r of ROLES) {
      const agent = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, `${r}.json`), "utf-8")) // nosemgrep: path-join-resolve-traversal — constant role names
      expect(agent.permissions).toBeDefined()
    }
    const orchestrator = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8"))
    expect(orchestrator.allowedTools).toEqual(withAsyncCompose(ORCHESTRATOR_V2).allowedTools)
    const composer = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-composer.json"), "utf-8"))
    expect(composer.tools).not.toContain("@sdpm/compose_slides")
  })

  it("refuses to write a definition without permissions, keeping the old output", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    const before = fs.readdirSync(dirs.agentsDir).sort()
    writeCatalogAgent("sdpm-translate", { permissions: null })
    expect(() => syncToAgentsDir(readSelection(dirs), dirs)).toThrow(/has no permissions/)
    expect(fs.readdirSync(dirs.agentsDir).sort()).toEqual(before)
  })
})

describe("selection persistence", () => {
  it("drops keys other than the four roles and the model, on read and on the next write", () => {
    fs.mkdirSync(path.dirname(dirs.configPath), { recursive: true })
    fs.writeFileSync(dirs.configPath, JSON.stringify({ spec: "sdpm-spec.json", vibe: "x.json", single: "y.json", composer: "sdpm-composer.json", model: "auto" }))
    const sel = readSelection(dirs)
    expect(sel).toEqual({ ...SELECTION_DEFAULTS, model: "auto" })
    writeSelection({ ...sel, ...({ spec: "z.json" } as object) } as typeof sel, dirs)
    expect(JSON.parse(fs.readFileSync(dirs.configPath, "utf-8"))).toEqual({ ...SELECTION_DEFAULTS, model: "auto" })
  })

  it("round-trips and merges over defaults", () => {
    writeSelection({ ...SELECTION_DEFAULTS, translate: "my-custom-translate.json", model: "m1" }, dirs)
    const sel = readSelection(dirs)
    expect(sel.translate).toBe("my-custom-translate.json")
    expect(sel.orchestrator).toBe("sdpm-orchestrator.json")
    expect(sel.style).toBe("sdpm-style.json")
    expect(sel.model).toBe("m1")
  })
})

describe("withAsyncCompose (the orchestrator dispatches with compose_slides)", () => {
  it("adds compose_slides and message_composer, and drops the composer sub-agent and use_subagent", () => {
    syncToAgentsDir(readSelection(dirs), dirs)
    writeCatalogAgent("sdpm-orchestrator", ORCHESTRATOR_V2)
    syncToAgentsDir(readSelection(dirs), dirs)
    const orchestrator = JSON.parse(fs.readFileSync(path.join(dirs.agentsDir, "sdpm-orchestrator.json"), "utf-8"))
    for (const key of ["tools", "allowedTools"]) {
      expect(orchestrator[key]).toEqual(expect.arrayContaining(["@sdpm/compose_slides", "@sdpm/message_composer"]))
      expect(orchestrator[key]).not.toContain("use_subagent")
      expect(orchestrator[key]).not.toContain("subagent/sdpm-composer")
    }
    expect(orchestrator.tools.filter((t: string) => t === "@sdpm/compose_slides")).toHaveLength(1)
    expect(orchestrator).not.toHaveProperty("toolsSettings")
    const mcp = orchestrator.permissions.rules.find((r: { capability: string }) => r.capability === "mcp")
    expect(mcp.match).toEqual(expect.arrayContaining(["sdpm/compose_slides", "sdpm/message_composer"]))
    expect(orchestrator.permissions.rules.some((r: { capability: string }) => r.capability === "subagent")).toBe(false)
  })

  it("keeps a custom orchestrator's other sub-agents and use_subagent", () => {
    const custom = { ...ORCHESTRATOR_V2, toolsSettings: { subagent: { availableAgents: ["sdpm-composer", "my-reviewer"], trustedAgents: ["sdpm-composer", "my-reviewer"] } } }
    const converted = withAsyncCompose(custom)
    expect(converted.toolsSettings).toEqual({ subagent: { availableAgents: ["my-reviewer"], trustedAgents: ["my-reviewer"] } })
    expect(converted.tools).toContain("use_subagent")
    expect(withPermissions(converted, "custom.json").tools).toContain("subagent/my-reviewer")
    expect(withPermissions(converted, "custom.json").tools).not.toContain("subagent/sdpm-composer")
  })

  it("does not add a duplicate, and a second sync with equal input leaves agents/ as it is", () => {
    expect(withAsyncCompose(withAsyncCompose(ORCHESTRATOR_V2))).toEqual(withAsyncCompose(ORCHESTRATOR_V2))
    syncToAgentsDir(readSelection(dirs), dirs)
    const inode = fs.statSync(dirs.agentsDir).ino
    syncToAgentsDir(readSelection(dirs), dirs)
    expect(fs.statSync(dirs.agentsDir).ino).toBe(inode)
  })
})
