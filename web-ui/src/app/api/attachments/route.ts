// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local-only raw attachment endpoint. Conversion is deferred to MCP tools. */

import { createHash, randomUUID } from "crypto"
import fs from "fs"
import path from "path"
import { DECK_ROOT } from "@/lib/local/deck-paths"
import { hasProcess } from "@/lib/local/acp-process"

const MAX_FILE_SIZE = 100 * 1024 * 1024
const SESSION_MAX_OBJECTS = 100
const SESSION_MAX_BYTES = 1024 * 1024 * 1024
const GLOBAL_MAX_OBJECTS = 500
const GLOBAL_MAX_BYTES = 5 * 1024 * 1024 * 1024
const RAW_TTL_MS = 90 * 24 * 60 * 60 * 1000
const TEMP_TTL_MS = 60 * 60 * 1000
const GC_INTERVAL_MS = 60 * 60 * 1000
const LEASE_TTL_MS = 10 * 60 * 1000

function sanitizeFilename(value: string): string {
  let name = value.replaceAll("/", "_").replaceAll("\\", "_").replaceAll("..", "_")
  name = [...name].filter((c) => c.charCodeAt(0) >= 0x20 && c.charCodeAt(0) !== 0x7f).join("").replace(/^\.+/, "")
  while (Buffer.byteLength(name, "utf8") > 255) name = name.slice(0, -1)
  if (!name || name.startsWith("[Attached:")) throw new Error("Invalid filename")
  return name
}

function regularFiles(root: string): string[] {
  if (!fs.existsSync(root)) return []
  const files: string[] = []
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const candidate = path.join(root, entry.name)
    if (entry.isDirectory()) files.push(...regularFiles(candidate))
    else if (entry.isFile() && ![".lease", ".gc-stamp", ".gc.lock"].includes(entry.name)) files.push(candidate)
  }
  return files
}

function usage(root: string): { count: number; bytes: number } {
  const files = regularFiles(root)
  return { count: files.length, bytes: files.reduce((total, file) => total + fs.statSync(file).size, 0) }
}

function maybeCollectExpired(root: string): void {
  fs.mkdirSync(root, { recursive: true, mode: 0o700 })
  const stamp = path.join(root, ".gc-stamp")
  const lock = path.join(root, ".gc.lock")
  const now = Date.now()
  try {
    if (now - fs.statSync(stamp).mtimeMs < GC_INTERVAL_MS) return
  } catch {}

  let lockFd: number
  try {
    lockFd = fs.openSync(lock, "wx", 0o600)
  } catch {
    return
  }
  try {
    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue
      const sessionDir = path.join(root, entry.name)
      let leased = false
      try { leased = now - fs.statSync(path.join(sessionDir, ".lease")).mtimeMs < LEASE_TTL_MS } catch {}
      if (leased || hasProcess(entry.name)) continue
      for (const file of regularFiles(sessionDir)) {
        try {
          const age = now - fs.statSync(file).mtimeMs
          const ttl = path.basename(file).startsWith(".") && file.endsWith(".tmp") ? TEMP_TTL_MS : RAW_TTL_MS
          if (age > ttl) fs.rmSync(file, { force: true })
        } catch {}
      }
    }
    fs.writeFileSync(stamp, String(now), { mode: 0o600 })
  } finally {
    fs.closeSync(lockFd)
    fs.rmSync(lock, { force: true })
  }
}

export async function POST(req: Request): Promise<Response> {
  const form = await req.formData()
  const sessionId = form.get("sessionId")
  const file = form.get("file")

  if (typeof sessionId !== "string" || !/^[A-Za-z0-9._-]{1,200}$/.test(sessionId)) {
    return Response.json({ error: "Valid sessionId required" }, { status: 400 })
  }
  if (!(file instanceof File)) return Response.json({ error: "file field missing" }, { status: 400 })
  if (file.size > MAX_FILE_SIZE) return Response.json({ error: "File exceeds 100MB limit" }, { status: 413 })

  try {
    const data = Buffer.from(await file.arrayBuffer())
    const digest = createHash("sha256").update(data).digest("hex")
    const filename = `${digest}_${sanitizeFilename(file.name)}`
    const root = path.resolve(DECK_ROOT, ".attachments")
    const sessionDir = path.resolve(root, sessionId)
    if (!sessionDir.startsWith(root + path.sep)) throw new Error("Invalid attachment path")
    maybeCollectExpired(root)
    fs.mkdirSync(sessionDir, { recursive: true, mode: 0o700 })
    const lease = path.join(sessionDir, ".lease")
    fs.closeSync(fs.openSync(lease, "a", 0o600))
    const now = new Date()
    fs.utimesSync(lease, now, now)

    const destination = path.join(sessionDir, filename)
    if (fs.existsSync(destination)) return Response.json({ source: destination })

    const sessionUsage = usage(sessionDir)
    const globalUsage = usage(root)
    if (sessionUsage.count >= SESSION_MAX_OBJECTS || sessionUsage.bytes + data.length > SESSION_MAX_BYTES) {
      return Response.json({ error: "Session attachment quota exceeded" }, { status: 429 })
    }
    if (globalUsage.count >= GLOBAL_MAX_OBJECTS || globalUsage.bytes + data.length > GLOBAL_MAX_BYTES) {
      return Response.json({ error: "Local attachment quota exceeded" }, { status: 429 })
    }

    const temp = path.join(sessionDir, `.${filename}.${randomUUID()}.tmp`)
    try {
      fs.writeFileSync(temp, data, { flag: "wx", mode: 0o600 })
      try {
        fs.linkSync(temp, destination)
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error
      }
    } finally {
      fs.rmSync(temp, { force: true })
    }
    return Response.json({ source: destination })
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 500 })
  }
}
