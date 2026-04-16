// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * outlineParser — Pure-function parser for outline markdown.
 *
 * Converts outline markdown (produced by spec-driven-presentation-maker agent) into structured
 * data that the OutlineView component can render as a timeline.
 *
 * Supports two formats:
 *   Skeleton: `- [slug] Message`
 *   Enriched: `- [slug] Message` with indented `- key: value` sub-items
 *
 * Slugs are kebab-case identifiers that map to slides/{slug}.json files.
 * Slide order is determined by line order in the outline.
 * Sub-item keys are fixed: what_to_say, evidence, what_to_show, notes.
 */

/** Valid sub-item key names (fixed by upstream planner-answers spec). */
export type SubItemKey = "what_to_say" | "evidence" | "what_to_show" | "notes"

/** A single sub-item attached to a slide. */
export interface OutlineSubItem {
  key: SubItemKey
  value: string
}

/** A parsed slide entry from the outline markdown. */
export interface OutlineSlide {
  slug: string
  message: string
  subItems: OutlineSubItem[]
}

/** Visual state of a slide in the timeline. */
export type SlideState = "skeleton" | "active" | "done"

/** Regex matching a slide entry line: `- [slug] Message` */
const SLIDE_RE = /^-\s*\[([a-z0-9-]+)\]\s*(.*)/

/** Regex matching a sub-item line: `  - key: value` */
const SUB_ITEM_RE = /^\s+-\s*(what_to_say|evidence|what_to_show|notes):\s*(.*)/

/**
 * Parse outline markdown into structured slide data.
 *
 * Processes the markdown line-by-line without relying on react-markdown's
 * AST, making it immune to formatting variations (blank lines, nesting depth).
 *
 * @param markdown - Raw outline markdown string
 * @returns Array of parsed slides in order
 */
export function parseOutline(markdown: string): OutlineSlide[] {
  const lines = markdown.split("\n")
  const slides: OutlineSlide[] = []
  let current: OutlineSlide | null = null

  for (const line of lines) {
    const slideMatch = line.match(SLIDE_RE)
    if (slideMatch) {
      current = {
        slug: slideMatch[1],
        message: slideMatch[2].trim(),
        subItems: [],
      }
      slides.push(current)
      continue
    }

    const subMatch = line.match(SUB_ITEM_RE)
    if (subMatch && current) {
      current.subItems.push({
        key: subMatch[1] as SubItemKey,
        value: subMatch[2].trim(),
      })
    }
    // Lines that match neither pattern are silently ignored (robustness).
  }

  return slides
}

/**
 * Determine the visual state of each slide based on sub-item presence.
 *
 * - skeleton: no sub-items (table-of-contents only)
 * - active: has sub-items AND is the last enriched slide (currently under review)
 * - done: has sub-items but is before the active slide (already reviewed)
 *
 * @param slides - Parsed slides from parseOutline
 * @returns Array of states, one per slide, in the same order
 */
export function resolveStates(slides: OutlineSlide[]): SlideState[] {
  // Find the index of the last slide that has sub-items.
  let lastEnrichedIndex = -1
  for (let i = slides.length - 1; i >= 0; i--) {
    if (slides[i].subItems.length > 0) {
      lastEnrichedIndex = i
      break
    }
  }

  return slides.map((slide, i) => {
    if (slide.subItems.length === 0) return "skeleton"
    if (i === lastEnrichedIndex) return "active"
    return "done"
  })
}
