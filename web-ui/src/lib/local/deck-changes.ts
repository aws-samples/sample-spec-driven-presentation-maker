// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * What counts as a deck's own files, for telling the chat what changed outside it (chat.ts).
 *
 * Every regular file under the deck directory counts (slides, specs, includes, attachments,
 * output.pptx / output.html, files the user added), found by a walk that does not follow
 * symlinks, except:
 * - a file or directory whose name starts with `.`, at any depth: the Web UI's chat files
 *   (deck-files.ts), temp files, stub markers, OS files;
 * - the top-level `preview/` (rendered previews), `compose/` (compose payloads derived from the
 *   slides) and `_work/` (the engine's scratch directory);
 * - `__pycache__/` at any depth and Office lock files (`~$…`).
 * The walk reads at most MAX_ENTRIES entries and MAX_DEPTH directory levels; past either it
 * warns once per deck and uses what it found.
 */
import fs from "fs"
import path from "path"

/** Entries read per walk, and directory levels below the deck root. */
export const MAX_ENTRIES = 5000
export const MAX_DEPTH = 8
/** Changed files listed by name; the rest are counted. */
export const MAX_LISTED = 20

const TOP_LEVEL_SKIPPED = new Set(["preview", "compose", "_work"])
const warned = new Set<string>()

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

function warnOnce(dir: string, message: string, ...args: unknown[]): void {
  if (warned.has(dir)) return
  warned.add(dir)
  console.warn(message, ...args)
}

function skipped(name: string, depth: number, isDir: boolean): boolean {
  if (name.startsWith(".")) return true
  if (isDir) return name === "__pycache__" || (depth === 1 && TOP_LEVEL_SKIPPED.has(name))
  return name.startsWith("~$")
}

/** Each deck file under `dir` (its `/`-separated path relative to `dir`) with its mtime; false when the deck root cannot be read. */
function walkDeckFiles(dir: string, visit: (rel: string, mtimeMs: number) => void): boolean {
  const stack: { abs: string; rel: string; depth: number }[] = [{ abs: dir, rel: "", depth: 0 }]
  let entries = 0
  let limited = false
  while (stack.length) {
    const current = stack.pop()!
    let dirents: fs.Dirent[]
    try {
      dirents = fs.readdirSync(current.abs, { withFileTypes: true })
    } catch (error) {
      if (current.depth === 0) {
        warnOnce(dir, "[acp] deck %s: could not read the deck's files: %s", dir, errorText(error))
        return false
      }
      continue // gone meanwhile
    }
    for (const dirent of dirents) {
      if (++entries > MAX_ENTRIES) {
        limited = true
        stack.length = 0
        break
      }
      const depth = current.depth + 1
      const isDir = dirent.isDirectory()
      if (skipped(dirent.name, depth, isDir)) continue
      const abs = path.join(current.abs, dirent.name) // nosemgrep: path-join-resolve-traversal — a name readdir returned, under the deck dir
      const rel = current.rel ? `${current.rel}/${dirent.name}` : dirent.name
      if (isDir) {
        if (depth >= MAX_DEPTH) limited = true
        else stack.push({ abs, rel, depth })
        continue
      }
      if (!dirent.isFile()) continue // symlinks are not followed
      try {
        visit(rel, fs.lstatSync(abs).mtimeMs)
      } catch { /* gone meanwhile */ }
    }
  }
  if (limited) warnOnce(dir, "[acp] deck %s: more than %d entries or %d levels; looking at the first ones only", dir, MAX_ENTRIES, MAX_DEPTH)
  return true
}

/** The deck files under `dir` changed after `since` (ms): the first MAX_LISTED by path, and how many more. */
export function changedDeckFiles(dir: string, since: number): { files: string[]; more: number } {
  const changed: string[] = []
  walkDeckFiles(dir, (rel, mtimeMs) => { if (mtimeMs > since) changed.push(rel) })
  changed.sort()
  return { files: changed.slice(0, MAX_LISTED), more: Math.max(0, changed.length - MAX_LISTED) }
}

/** The newest mtime (ms) among the deck files under `dir`; 0 when it has none. */
export function newestDeckFileMtime(dir: string): number {
  let newest = 0
  walkDeckFiles(dir, (_rel, mtimeMs) => { if (mtimeMs > newest) newest = mtimeMs })
  return newest
}
