// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local-only access to the kiro-cli session store. */
import crypto from "crypto"
import fs from "fs"
import { promises as fsp } from "fs"
import os from "os"
import path from "path"
import readline from "readline"

import type {
  KiroSessionSummary,
  KiroSessionsResponse,
  SessionOrigin,
} from "./kiro-sessions.types"

export const KIRO_SESSIONS_DIR = path.join(os.homedir(), ".kiro", "sessions", "cli")
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const RECENT_WINDOW_MS = 24 * 60 * 60 * 1000

export interface SessionMeta {
  session_id?: unknown
  cwd?: unknown
  updated_at?: unknown
  title?: unknown
  parent_session_id?: unknown
  session_state?: { agent_name?: unknown } | null
  [key: string]: unknown
}

interface SessionFilesOptions {
  dir?: string
}

function sessionsDir(dir?: string): string {
  return dir ?? process.env.SDPM_KIRO_SESSIONS_DIR ?? KIRO_SESSIONS_DIR
}

function assertSessionId(sessionId: string): void {
  if (!UUID_RE.test(sessionId)) throw new Error("invalid kiro session ID")
}

function sessionPath(sessionId: string, extension: ".json" | ".jsonl", dir?: string): string {
  assertSessionId(sessionId)
  return path.join(sessionsDir(dir), `${sessionId}${extension}`)
}

function agentName(meta: SessionMeta): string | null {
  const value = meta.session_state?.agent_name
  return typeof value === "string" ? value : null
}

export function isCandidate(meta: SessionMeta): boolean {
  const cwd = typeof meta.cwd === "string" ? meta.cwd : ""
  const agent = agentName(meta)
  return meta.parent_session_id == null
    && !agent?.startsWith("sdpm-")
    && !/[\\/]servers[\\/]local(?:[\\/]|$)/.test(cwd)
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

async function inspectLog(jsonlPath: string): Promise<{ messageCount: number; firstPrompt: string }> {
  let messageCount = 0
  let firstPrompt = ""
  let input: fs.ReadStream | null = null
  try {
    input = fs.createReadStream(jsonlPath, { encoding: "utf-8" })
    const lines = readline.createInterface({ input, crlfDelay: Infinity })
    for await (const line of lines) {
      try {
        const entry = JSON.parse(line) as unknown
        if (entry && typeof entry === "object" && (entry as Record<string, unknown>).kind === "Prompt") {
          messageCount++
          const text = promptText(entry)
          if (!firstPrompt && text !== null) firstPrompt = text
        }
      } catch {
        // An append interrupted mid-line must not hide otherwise valid sessions.
      }
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error
  } finally {
    input?.destroy()
  }
  return { messageCount, firstPrompt }
}

function firstCharacters(value: string, count: number): string {
  return Array.from(value).slice(0, count).join("")
}

async function summarize(sessionId: string, meta: SessionMeta, dir?: string): Promise<KiroSessionSummary> {
  const log = await inspectLog(sessionPath(sessionId, ".jsonl", dir))
  const cwd = typeof meta.cwd === "string" ? meta.cwd : ""
  const storedTitle = typeof meta.title === "string" ? meta.title : ""
  return {
    sessionId,
    title: storedTitle.trim() ? storedTitle : firstCharacters(log.firstPrompt, 60),
    cwd,
    project: path.basename(cwd),
    updatedAt: typeof meta.updated_at === "string" ? meta.updated_at : "",
    messageCount: log.messageCount,
    agentName: agentName(meta),
  }
}

function updatedTime(session: KiroSessionSummary): number {
  const timestamp = Date.parse(session.updatedAt)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

export async function listSessions(opts: { includeAll: boolean; dir?: string }): Promise<KiroSessionsResponse> {
  const dir = sessionsDir(opts.dir)
  let names: string[]
  try {
    names = await fsp.readdir(dir)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { groups: [], recent: [] }
    throw error
  }

  const records = (await Promise.all(names
    .filter((name) => name.endsWith(".json") && UUID_RE.test(name.slice(0, -5)))
    .map(async (name) => {
      const sessionId = name.slice(0, -5)
      try {
        const meta = JSON.parse(await fsp.readFile(path.join(dir, name), "utf-8")) as SessionMeta
        return { meta, summary: await summarize(sessionId, meta, dir), candidate: isCandidate(meta) }
      } catch {
        return null
      }
    })))
    .filter((record): record is NonNullable<typeof record> => record !== null)
    .sort((a, b) => updatedTime(b.summary) - updatedTime(a.summary))

  const grouped = new Map<string, KiroSessionSummary[]>()
  for (const record of records) {
    if (!opts.includeAll && !record.candidate) continue
    const sessions = grouped.get(record.summary.cwd) ?? []
    sessions.push(record.summary)
    grouped.set(record.summary.cwd, sessions)
  }

  const groups = Array.from(grouped, ([cwd, sessions]) => ({
    cwd,
    project: sessions[0]?.project ?? path.basename(cwd),
    sessions,
  }))
  const cutoff = Date.now() - RECENT_WINDOW_MS
  const recent = records
    .filter((record) => record.candidate && updatedTime(record.summary) >= cutoff)
    .slice(0, 3)
    .map((record) => record.summary)

  return { groups, recent }
}

export async function forkSession(
  sourceId: string,
  opts: SessionFilesOptions = {},
): Promise<{ newId: string; origin: SessionOrigin }> {
  assertSessionId(sourceId)
  const dir = sessionsDir(opts.dir)
  const sourceJson = sessionPath(sourceId, ".json", dir)
  const sourceJsonl = sessionPath(sourceId, ".jsonl", dir)
  const meta = JSON.parse(await fsp.readFile(sourceJson, "utf-8")) as SessionMeta
  const summary = await summarize(sourceId, meta, dir)
  const newId = crypto.randomUUID()
  const destinationJson = sessionPath(newId, ".json", dir)
  const destinationJsonl = sessionPath(newId, ".jsonl", dir)
  const forkedMeta: SessionMeta = {
    ...meta,
    session_id: newId,
    imported_from: { session_id: sourceId, forked_by: "sdpm-web-ui" },
  }

  try {
    await fsp.writeFile(destinationJson, `${JSON.stringify(forkedMeta, null, 2)}\n`, { flag: "wx" })
    await fsp.copyFile(sourceJsonl, destinationJsonl, fs.constants.COPYFILE_EXCL)
  } catch (error) {
    await Promise.allSettled([fsp.rm(destinationJson, { force: true }), fsp.rm(destinationJsonl, { force: true })])
    throw error
  }

  return {
    newId,
    origin: {
      sourceSessionId: sourceId,
      title: summary.title,
      cwd: summary.cwd,
      updatedAt: summary.updatedAt,
      forkedAt: new Date().toISOString(),
    },
  }
}

/** Remove only files created for a validated fork ID. */
export async function removeForkedSession(sessionId: string, opts: SessionFilesOptions = {}): Promise<void> {
  await Promise.allSettled([
    fsp.rm(sessionPath(sessionId, ".json", opts.dir), { force: true }),
    fsp.rm(sessionPath(sessionId, ".jsonl", opts.dir), { force: true }),
  ])
}
