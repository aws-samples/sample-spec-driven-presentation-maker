// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { addedSlugs, isPlaceholderSlug, parseOutlineDocument } from "./outlineDocument"
import { diffLines, diffStats, formatUnifiedDiff } from "./unifiedDiff"

export interface OutlineMessageCatalog {
  edited: string
  largeEdit: (count: number) => string
  placeholderSlugs: (slugs: string) => string
  polish: string
  overwritten: string
  display: (added: number, deleted: number) => string
}

export interface OutlineEditMessageInput {
  base: string
  text: string
  latestSeen: string
  polish: boolean
  catalog: OutlineMessageCatalog
}

export interface OutlineEditMessage {
  body: string
  displayContent: string
  added: number
  deleted: number
  placeholderSlugs: string[]
}

export function buildOutlineEditMessage({ base, text, latestSeen, polish, catalog }: OutlineEditMessageInput): OutlineEditMessage {
  const operations = diffLines(base, text)
  const stats = diffStats(operations)
  const unified = formatUnifiedDiff(operations)
  const unifiedLineCount = unified ? unified.split("\n").length : 0
  const placeholders = addedSlugs(parseOutlineDocument(base), parseOutlineDocument(text)).filter(isPlaceholderSlug)
  const paragraphs: string[] = [
    unifiedLineCount > 150
      ? catalog.largeEdit(stats.added + stats.deleted)
      : `${catalog.edited}\n\n\`\`\`diff\n${unified}\n\`\`\``,
  ]

  if (placeholders.length > 0) {
    paragraphs.push(catalog.placeholderSlugs(placeholders.map((slug) => `\`${slug}\``).join(", ")))
  }
  if (polish) paragraphs.push(catalog.polish)
  if (latestSeen !== base) paragraphs.push(catalog.overwritten)

  return {
    body: paragraphs.join("\n\n"),
    displayContent: catalog.display(stats.added, stats.deleted),
    added: stats.added,
    deleted: stats.deleted,
    placeholderSlugs: placeholders,
  }
}
