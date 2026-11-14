// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Containment check for paths built from request input under a local data directory. */
import fs from "fs"
import path from "path"

function isWithin(root: string, target: string): boolean {
  const prefix = root.endsWith(path.sep) ? root : root + path.sep
  return target === root || target.startsWith(prefix)
}

/**
 * Resolve `segments` under `root` and return the path to use, or null when it lies outside
 * `root`. Both sides are compared lexically and then after resolving symlinks (realpath), with
 * a separator boundary, so neither `..`, a symlink pointing out of `root`, nor a sibling such as
 * `<root>-other` gets through. An existing target is returned as its real path. A missing one
 * (ENOENT) is returned as the lexical path, so a reader's existence check turns it into a 404 and
 * a writer creates it, but only when its deepest existing ancestor also resolves inside `root`
 * and the target is not a dangling symlink: what a write creates stays inside `root` too.
 * Null as well when `root` itself is missing or cannot be resolved.
 */
export function resolveWithin(root: string, ...segments: string[]): string | null {
  // nosemgrep: path-join-resolve-traversal — server-side root; segments are checked below
  const base = path.resolve(root)
  // nosemgrep: path-join-resolve-traversal — containment is checked right below
  const full = path.resolve(base, ...segments)
  if (!isWithin(base, full)) return null
  let rootReal: string
  try {
    rootReal = fs.realpathSync.native(base)
  } catch {
    return null
  }
  try {
    const real = fs.realpathSync.native(full)
    return isWithin(rootReal, real) ? real : null
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "ENOENT") return null
  }
  // Missing target. An entry that exists but does not resolve is a dangling symlink.
  try {
    fs.lstatSync(full)
    return null
  } catch { /* nothing at the target itself */ }
  for (let dir = path.dirname(full); ; dir = path.dirname(dir)) {
    try {
      return isWithin(rootReal, fs.realpathSync.native(dir)) ? full : null
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT" || dir === base) return null
    }
  }
}
