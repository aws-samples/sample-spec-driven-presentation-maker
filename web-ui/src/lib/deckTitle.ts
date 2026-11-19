// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Display title for a deck name.
 *
 * Local decks are folders named `YYYYMMDD-HHMM-kebab-slug`. The timestamp is metadata
 * and the slug reads better as words, so the UI shows "Kebab slug" and keeps the
 * folder name for tooltips and identifiers. Names without that prefix (cloud decks,
 * hand-made folders) are returned unchanged.
 */

const STAMPED = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})-(.+)$/

export interface DeckDisplay {
  /** Human-readable title. */
  title: string
  /** Creation time taken from the folder prefix, when present. */
  createdAt: Date | null
}

export function deckDisplay(name: string): DeckDisplay {
  const m = STAMPED.exec(name)
  if (!m) return { title: name, createdAt: null }
  const [, y, mo, d, h, mi, slug] = m
  const words = slug.replace(/[-_]+/g, " ").trim()
  const title = words ? words.charAt(0).toUpperCase() + words.slice(1) : name
  const createdAt = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi))
  return { title, createdAt: Number.isNaN(createdAt.getTime()) ? null : createdAt }
}
