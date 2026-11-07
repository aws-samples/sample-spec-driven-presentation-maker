// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * acp-config.json: missing or broken files give the defaults; the new format's fields are
 * validated one by one; the old format keeps its command and environment and drops its args
 * (the real `--agent sdpm-spec` example); reading never writes. writeEngine keeps the command,
 * arguments and environment, moves an old file aside once and replaces the file atomically.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

let dir: string
let cfg: typeof import("./engine-config")
let warn: ReturnType<typeof vi.spyOn>

const file = (name = "acp-config.json") => path.resolve(dir, name) // nosemgrep: path-join-resolve-traversal — constant names in a tmpdir
const write = (value: unknown) => fs.writeFileSync(file(), typeof value === "string" ? value : JSON.stringify(value))

/** The old file a user still has (report S15): an agent list, `--agent sdpm-spec`, unused fields. */
const OLD_FORMAT = {
  activeAgent: "kiro-cli",
  agents: [{
    id: "kiro-cli", displayName: "Kiro CLI", path: "/opt/kiro/bin/kiro-cli", args: ["acp", "--agent", "sdpm-spec"],
    env: { AWS_PROFILE: "work" }, subagentTool: "use_subagent", subagentInstruction: "", restartOnNewChat: true, subagentQueryField: "query",
  }],
}

beforeEach(async () => {
  dir = fs.mkdtempSync(path.resolve(os.tmpdir(), "sdpm-acp-config-"))
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", dir)
  warn = vi.spyOn(console, "warn").mockImplementation(() => {})
  vi.resetModules()
  cfg = await import("./engine-config")
})

afterEach(() => {
  warn.mockRestore()
  vi.unstubAllEnvs()
  fs.rmSync(dir, { recursive: true, force: true })
})

const DEFAULTS = { version: 2, engine: "v2", command: "kiro-cli", commandArgs: [], env: {} }

describe("readEngineConfig", () => {
  it("gives the defaults without a file, silently", () => {
    expect(cfg.readEngineConfig()).toEqual(DEFAULTS)
    expect(cfg.DEFAULT_ENGINE).toBe("v2")
    expect(warn).not.toHaveBeenCalled()
  })

  it.each([["not JSON", "{broken"], ["not an object", "[1, 2]"], ["an unknown version", { version: 3, engine: "v3" }]])(
    "gives the defaults for a file that is %s, warns once and leaves it as it is",
    (_case, content) => {
      write(content)
      const before = fs.readFileSync(file(), "utf-8")
      expect(cfg.readEngineConfig()).toEqual(DEFAULTS)
      expect(cfg.readEngineConfig()).toEqual(DEFAULTS)
      expect(warn).toHaveBeenCalledTimes(1)
      expect(fs.readFileSync(file(), "utf-8")).toBe(before)
    },
  )

  it("reads the new format", () => {
    write({ version: 2, engine: "v3", command: "/usr/bin/node", commandArgs: ["stub.mjs"], env: { A: "1" } })
    expect(cfg.readEngineConfig()).toEqual({ version: 2, engine: "v3", command: "/usr/bin/node", commandArgs: ["stub.mjs"], env: { A: "1" } })
    expect(warn).not.toHaveBeenCalled()
  })

  it("replaces each invalid field with its default and warns about it", () => {
    write({ version: 2, engine: "v9", command: "", commandArgs: ["ok", 1], env: { A: "1", B: 2 } })
    expect(cfg.readEngineConfig()).toEqual({ ...DEFAULTS, env: { A: "1" } })
    expect(warn).toHaveBeenCalledTimes(4)
  })

  it("reads an old-format file's command and environment, not its args, with one warning, and does not rewrite it", () => {
    write(OLD_FORMAT)
    const before = fs.readFileSync(file(), "utf-8")
    expect(cfg.readEngineConfig()).toEqual({ ...DEFAULTS, command: "/opt/kiro/bin/kiro-cli", env: { AWS_PROFILE: "work" } })
    cfg.readEngineConfig()
    expect(warn).toHaveBeenCalledTimes(1)
    expect(warn.mock.calls[0].join(" ")).toContain("not used")
    expect(fs.readFileSync(file(), "utf-8")).toBe(before)
  })

  it("reads the first agent of an old-format file whose active agent is missing", () => {
    write({ activeAgent: "gone", agents: [{ id: "a", path: "kiro-a" }, { id: "b", path: "kiro-b" }] })
    expect(cfg.readEngineConfig().command).toBe("kiro-a")
  })
})

describe("writeEngine", () => {
  it("writes the new format with the defaults when there is no file", () => {
    expect(cfg.writeEngine("v3")).toEqual({ ...DEFAULTS, engine: "v3" })
    expect(JSON.parse(fs.readFileSync(file(), "utf-8"))).toEqual({ ...DEFAULTS, engine: "v3" })
    expect(fs.readdirSync(dir)).toEqual(["acp-config.json"])
  })

  it("keeps the command, its arguments and the environment", () => {
    write({ version: 2, engine: "v3", command: "/usr/bin/node", commandArgs: ["stub.mjs"], env: { A: "1" } })
    cfg.writeEngine("v2")
    expect(cfg.readEngineConfig()).toEqual({ version: 2, engine: "v2", command: "/usr/bin/node", commandArgs: ["stub.mjs"], env: { A: "1" } })
  })

  it("moves an old-format file to acp-config.v1.json.bak before writing the new one", () => {
    write(OLD_FORMAT)
    const old = fs.readFileSync(file(), "utf-8")
    cfg.writeEngine("v3")
    expect(fs.readFileSync(file("acp-config.v1.json.bak"), "utf-8")).toBe(old)
    expect(cfg.readEngineConfig()).toEqual({ ...DEFAULTS, engine: "v3", command: "/opt/kiro/bin/kiro-cli", env: { AWS_PROFILE: "work" } })
  })

  it("keeps an existing backup and overwrites the old file", () => {
    fs.writeFileSync(file("acp-config.v1.json.bak"), "earlier backup")
    write(OLD_FORMAT)
    cfg.writeEngine("v3")
    expect(fs.readFileSync(file("acp-config.v1.json.bak"), "utf-8")).toBe("earlier backup")
    expect(cfg.readEngineConfig().engine).toBe("v3")
    expect(fs.readdirSync(dir).sort()).toEqual(["acp-config.json", "acp-config.v1.json.bak"])
  })

  it("creates the directory", () => {
    fs.rmSync(dir, { recursive: true })
    cfg.writeEngine("v3")
    expect(cfg.readEngineConfig().engine).toBe("v3")
  })
})
