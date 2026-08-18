// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * outlineParser — Pure-function parser for outline markdown.
 *
 * Converts outline markdown (produced by spec-driven-presentation-maker agent) into structured
 * data that the OutlineView component can render.
 *
 * Returns a discriminated union array preserving document order:
 *   SlideEntry: `- [slug] Message` with optional indented sub-items
 *   SectionEntry: `## Heading` lines (markdown h2)
 *   ProseEntry: any other non-empty text (nothing is silently discarded)
 *
 * Supports two slide formats:
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

// ---------------------------------------------------------------------------
// Discriminated union entries
// ---------------------------------------------------------------------------

/** A parsed slide entry from the outline markdown. */
export interface SlideEntry {
  type: "slide"
  slug: string
  message: string
  subItems: OutlineSubItem[]
}

/** A section heading (## ...) entry. */
export interface SectionEntry {
  type: "section"
  title: string
}

/** Prose text that is neither a slide nor a section heading. */
export interface ProseEntry {
  type: "prose"
  text: string
}

/** Any entry in the parsed outline document. */
export type OutlineEntry = SlideEntry | SectionEntry | ProseEntry

// ---------------------------------------------------------------------------
// Backward-compatible aliases
// ---------------------------------------------------------------------------

/** @deprecated Use SlideEntry instead. Kept for backward compatibility. */
export type OutlineSlide = SlideEntry

/** Visual state of a slide in the timeline. */
export type SlideState = "skeleton" | "active" | "done"

// ---------------------------------------------------------------------------
// Regex patterns
// ---------------------------------------------------------------------------

/** Regex matching a slide entry line: `- [slug] Message` or legacy `- [N: Name] Message` */
const SLIDE_RE = /^-\s*\[([^\]]+)\]\s*(.*)/

/** Regex matching a sub-item line: `  - key: value` */
const SUB_ITEM_RE = /^\s+-\s*(what_to_say|evidence|what_to_show|notes):\s*(.*)/

/** Regex matching a section heading: `## Title` */
const SECTION_RE = /^##\s+(.+)/

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

/**
 * Parse outline markdown into structured entries preserving document order.
 *
 * Processes the markdown line-by-line. Every non-empty line is classified:
 * - Slide lines (`- [slug] Message`) become SlideEntry
 * - Section headings (`## Title`) become SectionEntry
 * - Sub-item lines are attached to the preceding SlideEntry
 * - All other non-blank text becomes ProseEntry
 *
 * Blank lines are the only lines that are not represented in the output
 * (they serve as visual separators in markdown but carry no semantic content).
 *
 * @param markdown - Raw outline markdown string
 * @returns Array of parsed entries in document order
 */
export function parseOutline(markdown: string): OutlineEntry[] {
  const lines = markdown.split("\n")
  const entries: OutlineEntry[] = []
  let currentSlide: SlideEntry | null = null

  for (const line of lines) {
    // Check for slide entry
    const slideMatch = line.match(SLIDE_RE)
    if (slideMatch) {
      currentSlide = {
        type: "slide",
        slug: slideMatch[1],
        message: slideMatch[2].trim(),
        subItems: [],
      }
      entries.push(currentSlide)
      continue
    }

    // Check for sub-item (must follow a slide)
    const subMatch = line.match(SUB_ITEM_RE)
    if (subMatch && currentSlide) {
      currentSlide.subItems.push({
        key: subMatch[1] as SubItemKey,
        value: subMatch[2].trim(),
      })
      continue
    }

    // Check for section heading
    const sectionMatch = line.match(SECTION_RE)
    if (sectionMatch) {
      currentSlide = null // section breaks slide context
      entries.push({ type: "section", title: sectionMatch[1].trim() })
      continue
    }

    // Blank lines are not represented (visual separators only)
    if (line.trim() === "") {
      continue
    }

    // Everything else is prose — preserve exactly
    currentSlide = null // prose breaks slide sub-item context
    entries.push({ type: "prose", text: line })
  }

  return entries
}

// ---------------------------------------------------------------------------
// State resolution (applies to slide entries only)
// ---------------------------------------------------------------------------

/**
 * Determine the visual state of each slide based on sub-item presence.
 *
 * - skeleton: no sub-items (table-of-contents only)
 * - active: has sub-items AND is the last enriched slide (currently under review)
 * - done: has sub-items but is before the active slide (already reviewed)
 *
 * This function accepts the full entry array but only assigns states to slide entries.
 * Non-slide entries receive no state (they are structural/content, not workflow items).
 *
 * @param entries - Parsed entries from parseOutline
 * @returns Map from entry index to SlideState (only slide indices are present)
 */
export function resolveStates(entries: OutlineEntry[]): Map<number, SlideState> {
  const states = new Map<number, SlideState>()

  // Find the last enriched slide index
  let lastEnrichedIndex = -1
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]
    if (entry.type === "slide" && entry.subItems.length > 0) {
      lastEnrichedIndex = i
      break
    }
  }

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]
    if (entry.type !== "slide") continue

    if (entry.subItems.length === 0) {
      states.set(i, "skeleton")
    } else if (i === lastEnrichedIndex) {
      states.set(i, "active")
    } else {
      states.set(i, "done")
    }
  }

  return states
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/** Extract only slide entries from the parsed outline. */
export function getSlideEntries(entries: OutlineEntry[]): SlideEntry[] {
  return entries.filter((e): e is SlideEntry => e.type === "slide")
}


