// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The models each engine last offered, kept next to acp-config.json (`engineConfigDir()`), so
 * the chat's model picker and Settings → Model can list them without starting kiro-cli:
 *
 *     {"version": 1, "engines": {"v3": [ModelOption, ...], "v2": [...]}}
 *
 * The process manager writes an engine's list when a session reports one that differs from the
 * last; reading is for when no session is live. A missing file is an empty list; a broken one,
 * another version or entries without a string `modelId` and `name` are dropped with one warning.
 * Writing replaces the file atomically and never throws (a failure is logged: only the list
 * shown before the next kiro-cli start is lost).
 */
import fs from "fs"
import path from "path"

import type { ModelOption } from "./engine"
import { engineConfigDir, type EngineId } from "./engine-config"

const CACHE_FILE = "acp-models.json"
const VERSION = 1

const cachePath = () => path.resolve(engineConfigDir(), CACHE_FILE)

const warned = new Set<string>()
function warnOnce(message: string): void {
  if (warned.has(message)) return
  warned.add(message)
  console.warn("[acp-models] %s", message)
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)

const isStringList = (value: unknown): value is string[] =>
  Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string")

/** One cached entry, with only the fields of ModelOption that have the right type; null when it has no id or name. */
function readEntry(value: unknown): ModelOption | null {
  if (!isObject(value) || typeof value.modelId !== "string" || !value.modelId || typeof value.name !== "string") return null
  return {
    modelId: value.modelId,
    name: value.name,
    ...(typeof value.description === "string" ? { description: value.description } : {}),
    ...(isStringList(value.effortLevels) ? { effortLevels: value.effortLevels } : {}),
    ...(typeof value.defaultEffort === "string" ? { defaultEffort: value.defaultEffort } : {}),
    ...(typeof value.rate === "number" && Number.isFinite(value.rate) ? { rate: value.rate } : {}),
  }
}

/** The file's engines, or {} when it is missing or unreadable (warned). */
function readAll(): Record<string, unknown> {
  let text: string
  try {
    text = fs.readFileSync(cachePath(), "utf-8")
  } catch {
    return {}
  }
  try {
    const raw: unknown = JSON.parse(text)
    if (isObject(raw) && raw.version === VERSION && isObject(raw.engines)) return raw.engines
  } catch { /* reported below */ }
  warnOnce(`${cachePath()} is not a version ${VERSION} model list; ignored`)
  return {}
}

/** The models an engine last offered ([] when none are known). */
export function readModelCache(engine: EngineId): ModelOption[] {
  const list = readAll()[engine]
  if (list === undefined) return []
  if (!Array.isArray(list)) {
    warnOnce(`${engine} in ${cachePath()} is not a list; ignored`)
    return []
  }
  const models = list.map(readEntry).filter((model): model is ModelOption => model !== null)
  if (models.length !== list.length) warnOnce(`${list.length - models.length} entries of ${engine} in ${cachePath()} have no modelId or name; dropped`)
  return models
}

/** Replace an engine's list, keeping the other engine's. */
export function writeModelCache(engine: EngineId, models: ModelOption[]): void {
  const dir = engineConfigDir()
  const tmp = path.resolve(dir, `${CACHE_FILE}.tmp-${process.pid}`)
  try {
    fs.mkdirSync(dir, { recursive: true })
    const engines = { ...readAll(), [engine]: models }
    fs.writeFileSync(tmp, JSON.stringify({ version: VERSION, engines }, null, 2) + "\n", "utf-8")
    fs.renameSync(tmp, cachePath())
  } catch (error) {
    console.warn("[acp-models] could not write %s: %s", cachePath(), error instanceof Error ? error.message : String(error))
    try { fs.rmSync(tmp, { force: true }) } catch { /* nothing to clean */ }
  }
}
