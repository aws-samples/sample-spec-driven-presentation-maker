// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Deck path resolution for Local mode.
 * Single source of truth for DECK_ROOT and safe path validation.
 * All filesystem access using a user-provided deckId MUST go through
 * resolveDeckDir() or resolveDeckPath() to prevent path traversal.
 */

import fs from "fs"
import path from "path"
import os from "os"

export const DECK_ROOT = process.env.SDPM_DECK_ROOT || path.join(os.homedir(), "Documents", "SDPM-Presentations")

/**
 * Resolve a user-provided deckId to an absolute directory path.
 * Returns null if deckId is invalid or escapes DECK_ROOT.
 *
 * Defense layers:
 *  1. Character allow-list (no separators/specials)
 *  2. Normalized prefix check
 *  3. realpath check (symlink-resistant)
 */
export function resolveDeckDir(deckId: string): string | null {
  if (!/^[A-Za-z0-9._-]+$/.test(deckId) || deckId.startsWith(".")) return null

  const root = path.resolve(DECK_ROOT)
  const dir = path.resolve(root, deckId)
  if (dir !== root && !dir.startsWith(root + path.sep)) return null

  try {
    const rootReal = fs.realpathSync.native(root)
    const dirReal = fs.realpathSync.native(dir)
    if (dirReal !== rootReal && !dirReal.startsWith(rootReal + path.sep)) return null
    return dirReal
  } catch {
    return null
  }
}

/** deck.json `slideSize` as {width, height} px (1920x1080 when missing or invalid). */
export function readSlideSize(deckJson: Record<string, unknown>): { width: number; height: number } {
  const size = deckJson.slideSize as { width?: unknown; height?: unknown } | undefined
  const ok = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0
  return size && ok(size.width) && ok(size.height) ? { width: size.width, height: size.height } : { width: 1920, height: 1080 }
}

/**
 * Resolve a full path under a deck (deckId + subpath segments).
 * Returns null if any segment escapes the deck directory.
 */
export function resolveDeckPath(deckId: string, ...subpath: string[]): string | null {
  const dir = resolveDeckDir(deckId)
  if (!dir) return null

  const full = path.resolve(dir, ...subpath)
  if (full !== dir && !full.startsWith(dir + path.sep)) return null
  return full
}
