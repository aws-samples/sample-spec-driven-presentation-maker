// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * How the Local Web UI starts kiro-cli: `servers/local/.sdpm/acp-config.json` (the directory is
 * `SDPM_ACP_CONFIG_DIR` when set, which E2E points at its sandbox).
 *
 *     {"version": 2, "engine": "v2" | "v3", "command": "kiro-cli", "commandArgs": [], "env": {}}
 *
 * Every field is optional and an invalid one falls back to its default with one console.warn:
 * - `engine`: the agent engine (default DEFAULT_ENGINE). The engine adapter adds its own launch
 *   arguments (`EngineAdapter.spawnArgs`); the file cannot change them.
 * - `command` / `commandArgs`: what is spawned (no shell), commandArgs before the engine's
 *   arguments (E2E: node and its stub agent).
 * - `env`: string values added to the process environment.
 * A `version` other than 2 makes the whole file ignored. A file without `version` is the old
 * format (`{activeAgent, agents: [{id, path, args, env, ...}]}`): the active agent's `path` and
 * `env` are read, its `args` are not (an old `--agent sdpm-spec` would start the wrong agent, and
 * any V2-only flag keeps kiro-cli on V2).
 *
 * Reading never writes. `writeEngine` is the only writer: it keeps the command and environment
 * read here, moves an old-format file aside to `acp-config.v1.json.bak` first (unless that
 * exists), and replaces the file atomically.
 */
import fs from "fs"
import path from "path"

export const ENGINE_IDS = ["v2", "v3"] as const
export type EngineId = (typeof ENGINE_IDS)[number]

/** The engine used when the file does not choose one. */
export const DEFAULT_ENGINE: EngineId = "v2"

export interface EngineConfig {
  version: 2
  engine: EngineId
  command: string
  commandArgs: string[]
  env: Record<string, string>
}

const CONFIG_FILE = "acp-config.json"
const OLD_FORMAT_BACKUP = "acp-config.v1.json.bak"
const DEFAULT_COMMAND = "kiro-cli"

export function isEngineId(value: unknown): value is EngineId {
  return typeof value === "string" && (ENGINE_IDS as readonly string[]).includes(value)
}

/** The directory of acp-config.json (read on every call, so a test can point it elsewhere). */
export function engineConfigDir(): string {
  return process.env.SDPM_ACP_CONFIG_DIR || path.resolve(process.cwd(), "..", "servers", "local", ".sdpm")
}

const configPath = () => path.resolve(engineConfigDir(), CONFIG_FILE)

/** Each distinct warning once per server process: the file is read on every kiro-cli start. */
const warned = new Set<string>()
function warnOnce(message: string): void {
  if (warned.has(message)) return
  warned.add(message)
  console.warn("[acp-config] %s", message)
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)

const defaults = (): EngineConfig => ({ version: 2, engine: DEFAULT_ENGINE, command: DEFAULT_COMMAND, commandArgs: [], env: {} })

function readEnv(value: unknown): Record<string, string> {
  if (value === undefined) return {}
  if (!isObject(value)) {
    warnOnce("env is not an object; ignored")
    return {}
  }
  const env: Record<string, string> = {}
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry === "string") env[key] = entry
    else warnOnce(`env.${key} is not a string; ignored`)
  }
  return env
}

function readCommand(value: unknown): string {
  if (value === undefined) return DEFAULT_COMMAND
  if (typeof value === "string" && value) return value
  warnOnce(`command is not a non-empty string; using ${DEFAULT_COMMAND}`)
  return DEFAULT_COMMAND
}

function fromVersion2(raw: Record<string, unknown>): EngineConfig {
  let engine = DEFAULT_ENGINE
  if (raw.engine !== undefined) {
    if (isEngineId(raw.engine)) engine = raw.engine
    else warnOnce(`engine ${JSON.stringify(raw.engine)} is not one of ${ENGINE_IDS.join(", ")}; using ${DEFAULT_ENGINE}`)
  }
  let commandArgs: string[] = []
  if (raw.commandArgs !== undefined) {
    if (Array.isArray(raw.commandArgs) && raw.commandArgs.every((arg) => typeof arg === "string")) commandArgs = raw.commandArgs
    else warnOnce("commandArgs is not an array of strings; ignored")
  }
  return { version: 2, engine, command: readCommand(raw.command), commandArgs, env: readEnv(raw.env) }
}

/** The old `{activeAgent, agents}` format: the active agent's command and environment. */
function fromOldFormat(raw: Record<string, unknown>): EngineConfig {
  const agents = Array.isArray(raw.agents) ? raw.agents.filter(isObject) : []
  const active = agents.find((agent) => agent.id === raw.activeAgent) ?? agents[0]
  if (!active) return defaults()
  if (Array.isArray(active.args) && active.args.length) {
    warnOnce(`the old-format args ${JSON.stringify(active.args)} are not used: the agent engine (Settings → Agent engine) sets kiro-cli's arguments`)
  }
  return { ...defaults(), command: readCommand(active.path), env: readEnv(active.env) }
}

function readRaw(): { raw: Record<string, unknown> | null; exists: boolean } {
  let text: string
  try {
    text = fs.readFileSync(configPath(), "utf-8")
  } catch {
    return { raw: null, exists: false }
  }
  try {
    const raw: unknown = JSON.parse(text)
    if (isObject(raw)) return { raw, exists: true }
  } catch { /* reported below */ }
  warnOnce(`${configPath()} is not a JSON object; using the defaults`)
  return { raw: null, exists: true }
}

export function readEngineConfig(): EngineConfig {
  const { raw } = readRaw()
  if (!raw) return defaults()
  if (raw.version === undefined) return fromOldFormat(raw)
  if (raw.version !== 2) {
    warnOnce(`${configPath()} has version ${JSON.stringify(raw.version)}, which this app does not read; using the defaults`)
    return defaults()
  }
  return fromVersion2(raw)
}

/** Save the engine (the Settings choice), keeping the command and environment in use. */
export function writeEngine(engine: EngineId): EngineConfig {
  const current = readEngineConfig()
  const next: EngineConfig = { version: 2, engine, command: current.command, commandArgs: current.commandArgs, env: current.env }
  const dir = engineConfigDir()
  fs.mkdirSync(dir, { recursive: true })
  const { raw } = readRaw()
  if (raw && raw.version === undefined) {
    const backup = path.resolve(dir, OLD_FORMAT_BACKUP)
    if (!fs.existsSync(backup)) fs.renameSync(configPath(), backup)
  }
  const tmp = path.resolve(dir, `${CONFIG_FILE}.tmp-${process.pid}`)
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2) + "\n", "utf-8")
  fs.renameSync(tmp, configPath())
  return next
}
