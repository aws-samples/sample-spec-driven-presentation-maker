// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/** The two candidate kinds the `/` picker offers. */
export type PickerKind = "template" | "style"

/** A single template/style candidate shown in the `/` picker. */
export interface PickerItem {
  kind: PickerKind
  name: string
  description: string
  source: "builtin" | "user"
  pinned: boolean // style only; templates are always false
  themeColors?: Record<string, string> // template only
  fonts?: { fullwidth?: string | null; halfwidth?: string | null }
  layoutCount?: number // template only
  html?: string // style only (cover preview)
}

/** Token grammar shared by insertion (`buildToken`) and detection (`parseTokens`, `ChatMessage`). */
export const SLASH_TOKEN_RE = /@(template|style):(?:"([^"]+)"|([A-Za-z0-9._-]+))/g

/**
 * Same grammar without capturing groups — for embedding inside another regex
 * (e.g. a `String.split` pattern, where inner captures would leak into the output).
 */
export const SLASH_TOKEN_SOURCE = '@(?:template|style):(?:"[^"]+"|[A-Za-z0-9._-]+)'

const BARE_NAME_RE = /^[A-Za-z0-9._-]+$/
const KIND_WORDS: PickerKind[] = ["template", "style"]

/**
 * Detect the `/` fragment ending at `caret`, if the picker should be open (R1.1-R1.3, R3.3).
 *
 * @param text - Full textarea value
 * @param caret - Caret offset into `text`
 * @returns The fragment's start offset (position of `/`) and its query text, or null if the
 *   picker should not open/stay open for this text+caret combination.
 */
export function detectSlashFragment(text: string, caret: number): { start: number; query: string } | null {
  const upToCaret = text.slice(0, caret)
  const start = upToCaret.lastIndexOf("/")
  if (start < 0) return null

  const before = start === 0 ? undefined : text[start - 1]
  const atLineStartOrAfterSpace = before === undefined || before === "\n" || before === " " || before === "\t"
  if (!atLineStartOrAfterSpace) return null

  const fragment = text.slice(start + 1, caret)
  if (fragment.includes("\n")) return null

  if (!isQueryWhitespaceAllowed(fragment)) return null

  return { start, query: fragment }
}

/**
 * Whether `query`'s whitespace usage is allowed to keep the picker open (R3.2/R3.3).
 * A single space is only allowed right after a word that exactly matches a PickerKind.
 */
function isQueryWhitespaceAllowed(query: string): boolean {
  if (!/\s/.test(query)) return true

  const firstSpace = query.indexOf(" ")
  if (firstSpace < 0) return false
  const firstWord = query.slice(0, firstSpace)
  if (!isPickerKind(firstWord)) return false

  const rest = query.slice(firstSpace)
  // Exactly one ASCII space, then no further whitespace in the remainder.
  return rest.startsWith(" ") && !/\s/.test(rest.slice(1))
}

function isPickerKind(word: string): word is PickerKind {
  return (KIND_WORDS as string[]).includes(word)
}

/**
 * Split a query into an optional kind filter and the remaining search term (R3.1/R3.2).
 *
 * @param query - Raw query captured after `/`
 */
export function splitQuery(query: string): { kind: PickerKind | null; term: string } {
  const spaceIndex = query.search(/\s/)
  if (spaceIndex < 0) {
    return { kind: null, term: query }
  }

  const firstWord = query.slice(0, spaceIndex)
  if (isPickerKind(firstWord)) {
    return { kind: firstWord, term: query.slice(spaceIndex + 1) }
  }

  // Should not normally be reached (detectSlashFragment already rejects this), but stay
  // defensive for direct callers of splitQuery.
  return { kind: null, term: query }
}

const SOURCE_RANK: Record<PickerItem["source"], number> = { user: 1, builtin: 2 }

/** Stable sort key: pinned first, then CUSTOM (user) before builtin (R4.2). */
function sortRank(item: PickerItem): number {
  if (item.pinned) return 0
  return SOURCE_RANK[item.source]
}

function stableSortByRank(items: PickerItem[]): PickerItem[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => sortRank(a.item) - sortRank(b.item) || a.index - b.index)
    .map(({ item }) => item)
}

const KIND_ORDER: Record<PickerKind, number> = { template: 0, style: 1 }

/**
 * Filter and order candidates for the given raw query (R3.1, R3.2, R4.1, R4.2).
 *
 * @param items - All available candidates (any order)
 * @param query - Raw query captured after `/` (see `detectSlashFragment`)
 */
export function filterItems(items: PickerItem[], query: string): PickerItem[] {
  const { kind, term } = splitQuery(query)
  const needle = term.toLowerCase()

  let matched: PickerItem[]
  if (kind !== null) {
    // R3.2: section-scoped filter — only that kind, filtered by name/description.
    matched = items.filter((item) => item.kind === kind && matchesNameOrDescription(item, needle))
  } else {
    matched = items.filter((item) => {
      if (matchesNameOrDescription(item, needle)) return true
      // R3.1: a kind-name match keeps the whole section.
      return needle.length > 0 && item.kind.includes(needle)
    })
  }

  const byKind = new Map<PickerKind, PickerItem[]>()
  for (const item of matched) {
    const bucket = byKind.get(item.kind)
    if (bucket) bucket.push(item)
    else byKind.set(item.kind, [item])
  }

  const orderedKinds = [...byKind.keys()].sort((a, b) => KIND_ORDER[a] - KIND_ORDER[b])
  return orderedKinds.flatMap((k) => stableSortByRank(byKind.get(k) ?? []))
}

function matchesNameOrDescription(item: PickerItem, needleLower: string): boolean {
  if (needleLower.length === 0) return true
  return item.name.toLowerCase().includes(needleLower) || item.description.toLowerCase().includes(needleLower)
}

/**
 * Build the insertion text for a confirmed picker item (R6.1, R11.2).
 * Quotes the name when it falls outside `[A-Za-z0-9._-]+`; always ends with one trailing space.
 *
 * @param item - The kind/name pair to render as a token
 */
export function buildToken(item: Pick<PickerItem, "kind" | "name">): string {
  const name = BARE_NAME_RE.test(item.name) ? item.name : `"${item.name}"`
  return `@${item.kind}:${name} `
}

/** A `@template:`/`@style:` token located within free-form text (R12.3). */
export interface TokenMatch {
  kind: PickerKind
  name: string
  start: number
  end: number
}

/**
 * Locate every `@template:<name>` / `@style:<name>` token within `text`.
 *
 * @param text - Chat input or message text to scan
 */
export function parseTokens(text: string): TokenMatch[] {
  const matches: TokenMatch[] = []
  for (const match of text.matchAll(SLASH_TOKEN_RE)) {
    const kind = match[1] as PickerKind
    const name = match[2] ?? match[3] ?? ""
    const start = match.index ?? 0
    matches.push({ kind, name, start, end: start + match[0].length })
  }
  return matches
}
