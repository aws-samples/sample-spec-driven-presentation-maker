// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V2's session store: one `{uuid}.json` (metadata) and `{uuid}.jsonl` (log) per session in
 * `<KIRO_HOME>/sessions/cli` (`SDPM_KIRO_SESSIONS_DIR` overrides it). V2 lists it by reading the
 * files, without kiro-cli; V3 can open these sessions too (it imports them on load or fork).
 *
 * A V2 fork is a file copy under a new UUID (with `imported_from`), which V2 then loads; the
 * source's files are never written.
 */
import crypto from "crypto"
import fs from "fs"
import { promises as fsp } from "fs"
import os from "os"
import path from "path"
import readline from "readline"

import type { StoredSession } from "../../engine"

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export interface V2SessionMeta {
  session_id?: unknown
  cwd?: unknown
  updated_at?: unknown
  title?: unknown
  parent_session_id?: unknown
  session_state?: { agent_name?: unknown } | null
  [key: string]: unknown
}

/** V2's store: `SDPM_KIRO_SESSIONS_DIR`, else `<KIRO_HOME>/sessions/cli` of kiro-cli's environment, else `~/.kiro/sessions/cli`. */
export function v2SessionsDir(env: NodeJS.ProcessEnv): string {
  if (env.SDPM_KIRO_SESSIONS_DIR) return env.SDPM_KIRO_SESSIONS_DIR
  const kiroHome = env.KIRO_HOME || path.join(os.homedir(), ".kiro")
  return path.join(kiroHome, "sessions", "cli") // nosemgrep: path-join-resolve-traversal — KIRO_HOME of the server's own environment (trusted config), constant segments
}

export function isV2SessionId(sessionId: string): boolean {
  return UUID_RE.test(sessionId)
}

function assertSessionId(sessionId: string): void {
  if (!isV2SessionId(sessionId)) throw new Error("invalid kiro session ID")
}

function sessionPath(sessionId: string, extension: ".json" | ".jsonl", dir: string): string {
  assertSessionId(sessionId)
  // Same defence layers as resolveDeckDir(): allow-list above, then a normalized
  // prefix check on the resolved path so the file can only ever be a direct child
  // of the sessions directory.
  const root = path.resolve(dir) // nosemgrep: path-join-resolve-traversal — trusted config, not user input
  const resolved = path.resolve(root, `${sessionId}${extension}`) // nosemgrep: path-join-resolve-traversal — UUID allow-list above, containment check below
  if (!resolved.startsWith(root + path.sep) || path.dirname(resolved) !== root) {
    throw new Error("invalid kiro session ID")
  }
  return resolved
}

function agentName(meta: V2SessionMeta): string | null {
  const value = meta.session_state?.agent_name
  return typeof value === "string" ? value : null
}

function promptText(entry: unknown): string | null {
  if (!entry || typeof entry !== "object") return null
  const record = entry as Record<string, unknown>
  if (record.kind !== "Prompt") return null
  const data = record.data
  if (!data || typeof data !== "object") return null
  const content = (data as Record<string, unknown>).content
  if (!Array.isArray(content)) return null
  for (const part of content) {
    if (!part || typeof part !== "object") continue
    const item = part as Record<string, unknown>
    if (item.kind === "text" && typeof item.data === "string") return item.data
  }
  return null
}

/**
 * First user prompt in a `.jsonl` log, used only as a title fallback.
 *
 * Stops at the first match: logs reach hundreds of MB, and listing must never
 * scale with their size. Everything else the picker shows comes from `.json`.
 */
async function readFirstPrompt(jsonlPath: string): Promise<string> {
  let input: fs.ReadStream | null = null
  try {
    input = fs.createReadStream(jsonlPath, { encoding: "utf-8" })
    const lines = readline.createInterface({ input, crlfDelay: Infinity })
    for await (const line of lines) {
      try {
        const text = promptText(JSON.parse(line) as unknown)
        if (text !== null) return text
      } catch {
        // An append interrupted mid-line must not hide otherwise valid sessions.
      }
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error
  } finally {
    input?.destroy()
  }
  return ""
}

function firstCharacters(value: string, count: number): string {
  return Array.from(value).slice(0, count).join("")
}

async function summarize(sessionId: string, meta: V2SessionMeta, dir: string): Promise<StoredSession> {
  const storedTitle = typeof meta.title === "string" ? meta.title : ""
  const title = storedTitle.trim()
    ? storedTitle
    : firstCharacters(await readFirstPrompt(sessionPath(sessionId, ".jsonl", dir)), 60)
  return {
    sessionId,
    engine: "v2",
    title,
    cwd: typeof meta.cwd === "string" ? meta.cwd : "",
    updatedAt: typeof meta.updated_at === "string" ? meta.updated_at : "",
    agentName: agentName(meta),
    ...(meta.parent_session_id != null ? { subagent: true } : {}),
  }
}

/** Every readable session in V2's store; a missing store is empty. */
export async function listV2Sessions(dir: string): Promise<StoredSession[]> {
  let names: string[]
  try {
    names = await fsp.readdir(dir)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return []
    throw error
  }
  const sessions = await Promise.all(names
    .filter((name) => name.endsWith(".json") && UUID_RE.test(name.slice(0, -5)))
    .map(async (name) => {
      try {
        // nosemgrep: path-join-resolve-traversal — `name` comes from readdir and passed the UUID filter above
        const meta = JSON.parse(await fsp.readFile(path.join(dir, name), "utf-8")) as V2SessionMeta
        return await summarize(name.slice(0, -5), meta, dir)
      } catch {
        return null
      }
    }))
  return sessions.filter((session): session is StoredSession => session !== null)
}

/** Copy a stored session under a new UUID (`imported_from` = the source); returns the new id. */
export async function copyStoredSession(sourceId: string, dir: string): Promise<string> {
  assertSessionId(sourceId)
  const meta = JSON.parse(await fsp.readFile(sessionPath(sourceId, ".json", dir), "utf-8")) as V2SessionMeta
  const newId = crypto.randomUUID()
  const destinationJson = sessionPath(newId, ".json", dir)
  const destinationJsonl = sessionPath(newId, ".jsonl", dir)
  const forkedMeta: V2SessionMeta = {
    ...meta,
    session_id: newId,
    // kiro-cli reads this as a plain string; an object makes `session/load` fail
    // with "failed to parse session metadata" (the /chat load convention is the path or id).
    imported_from: sourceId,
  }
  try {
    await fsp.writeFile(destinationJson, `${JSON.stringify(forkedMeta, null, 2)}\n`, { flag: "wx" })
    await fsp.copyFile(sessionPath(sourceId, ".jsonl", dir), destinationJsonl, fs.constants.COPYFILE_EXCL)
  } catch (error) {
    await removeStoredSession(newId, dir)
    throw error
  }
  return newId
}

/** Remove a stored session's files (only a validated UUID, inside the store). */
export async function removeStoredSession(sessionId: string, dir: string): Promise<void> {
  await Promise.allSettled([
    fsp.rm(sessionPath(sessionId, ".json", dir), { force: true }),
    fsp.rm(sessionPath(sessionId, ".jsonl", dir), { force: true }),
  ])
}
