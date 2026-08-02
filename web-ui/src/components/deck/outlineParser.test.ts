// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * outlineParser tests — discriminated union parsing, state resolution,
 * backward compatibility, and view mode derivation.
 */

import { describe, it, expect } from "vitest"
import {
  parseOutline,
  resolveStates,
  getSlideEntries,
} from "./outlineParser"
import type { OutlineEntry, SlideEntry, SectionEntry, ProseEntry } from "./outlineParser"

describe("outlineParser", () => {
  describe("parseOutline — discriminated union", () => {
    it("parses slide entries with type=slide", () => {
      const md = "- [intro] Welcome slide\n- [data] Key metrics"
      const entries = parseOutline(md)
      expect(entries).toHaveLength(2)
      expect(entries[0]).toEqual({
        type: "slide",
        slug: "intro",
        message: "Welcome slide",
        subItems: [],
      })
      expect(entries[1]).toEqual({
        type: "slide",
        slug: "data",
        message: "Key metrics",
        subItems: [],
      })
    })

    it("parses section headings with type=section", () => {
      const md = "## Introduction\n\n- [intro] Hello"
      const entries = parseOutline(md)
      expect(entries).toHaveLength(2)
      expect(entries[0]).toEqual({ type: "section", title: "Introduction" })
      expect(entries[1].type).toBe("slide")
    })

    it("preserves prose lines with type=prose", () => {
      const md = "This is introductory text\n\n- [slide-1] First slide"
      const entries = parseOutline(md)
      expect(entries).toHaveLength(2)
      expect(entries[0]).toEqual({ type: "prose", text: "This is introductory text" })
      expect(entries[1].type).toBe("slide")
    })

    it("preserves document order across all entry types", () => {
      const md = [
        "# Deck Title",
        "",
        "## Part One",
        "Some context about this section.",
        "",
        "- [slide-1] First slide",
        "  - what_to_say: Hello world",
        "",
        "## Part Two",
        "",
        "- [slide-2] Second slide",
        "More trailing text",
      ].join("\n")
      const entries = parseOutline(md)
      const types = entries.map((e) => e.type)
      // # heading is prose (only ## is section), "Some context" is prose,
      // then section, slide, section, slide, prose
      expect(types).toEqual(["prose", "section", "prose", "slide", "section", "slide", "prose"])
    })

    it("does not silently discard any non-blank content", () => {
      const md = [
        "Preamble line",
        "## Section A",
        "- [a1] Slide A1",
        "Random text between slides",
        "- [a2] Slide A2",
        "## Section B",
        "- [b1] Slide B1",
        "Epilogue",
      ].join("\n")
      const entries = parseOutline(md)
      // Every non-blank line should be present
      expect(entries).toHaveLength(8)
      expect(entries.map((e) => e.type)).toEqual([
        "prose", "section", "slide", "prose", "slide", "section", "slide", "prose",
      ])
    })

    it("blank lines are not represented in output", () => {
      const md = "\n\n- [s1] Slide\n\n\n- [s2] Slide\n\n"
      const entries = parseOutline(md)
      expect(entries).toHaveLength(2)
      expect(entries.every((e) => e.type === "slide")).toBe(true)
    })

    it("attaches sub-items to the preceding slide entry", () => {
      const md = [
        "- [slide-1] My Slide",
        "  - what_to_say: This is what I say",
        "  - evidence: Data shows X",
        "  - what_to_show: Bar chart",
        "  - notes: Remember to emphasize Y",
      ].join("\n")
      const entries = parseOutline(md)
      expect(entries).toHaveLength(1)
      const slide = entries[0] as SlideEntry
      expect(slide.subItems).toHaveLength(4)
      expect(slide.subItems[0]).toEqual({ key: "what_to_say", value: "This is what I say" })
      expect(slide.subItems[1]).toEqual({ key: "evidence", value: "Data shows X" })
      expect(slide.subItems[2]).toEqual({ key: "what_to_show", value: "Bar chart" })
      expect(slide.subItems[3]).toEqual({ key: "notes", value: "Remember to emphasize Y" })
    })

    it("sub-items without a preceding slide become prose", () => {
      const md = "  - what_to_say: orphan sub-item"
      const entries = parseOutline(md)
      // The sub-item regex won't match without a current slide, treated as prose
      expect(entries).toHaveLength(1)
      expect(entries[0].type).toBe("prose")
    })

    it("section heading breaks sub-item attachment context", () => {
      const md = [
        "- [s1] Slide",
        "## New Section",
        "  - what_to_say: This should not attach to s1",
      ].join("\n")
      const entries = parseOutline(md)
      expect(entries).toHaveLength(3)
      const slide = entries[0] as SlideEntry
      expect(slide.subItems).toHaveLength(0)
      expect(entries[2].type).toBe("prose") // orphan sub-item becomes prose
    })

    it("handles legacy [N: Name] slug format", () => {
      const md = "- [1: Introduction] Welcome to the deck"
      const entries = parseOutline(md)
      expect(entries).toHaveLength(1)
      const slide = entries[0] as SlideEntry
      expect(slide.slug).toBe("1: Introduction")
      expect(slide.message).toBe("Welcome to the deck")
    })

    it("handles empty message in slide entries", () => {
      const md = "- [my-slug]"
      const entries = parseOutline(md)
      expect(entries).toHaveLength(1)
      const slide = entries[0] as SlideEntry
      expect(slide.slug).toBe("my-slug")
      expect(slide.message).toBe("")
    })

    it("recognizes only ## as section headings (not # or ###)", () => {
      const md = "# H1 Title\n## H2 Section\n### H3 Subsection"
      const entries = parseOutline(md)
      const sections = entries.filter((e) => e.type === "section")
      expect(sections).toHaveLength(1)
      expect((sections[0] as SectionEntry).title).toBe("H2 Section")
      // # and ### become prose
      const proseEntries = entries.filter((e) => e.type === "prose")
      expect(proseEntries).toHaveLength(2)
    })

    it("handles unrecognized content gracefully as prose", () => {
      const md = [
        "---",
        "metadata: value",
        "> blockquote",
        "1. numbered list",
        "* unordered list",
        "```code```",
      ].join("\n")
      const entries = parseOutline(md)
      // All should become prose (none are slides or ## sections)
      expect(entries.every((e) => e.type === "prose")).toBe(true)
      expect(entries).toHaveLength(6)
    })
  })

  describe("resolveStates — slide state resolution", () => {
    it("marks skeleton for slides with no sub-items", () => {
      const entries = parseOutline("- [s1] A\n- [s2] B\n- [s3] C")
      const states = resolveStates(entries)
      expect(states.get(0)).toBe("skeleton")
      expect(states.get(1)).toBe("skeleton")
      expect(states.get(2)).toBe("skeleton")
    })

    it("marks the last enriched slide as active", () => {
      const md = [
        "- [s1] A",
        "  - what_to_say: Hello",
        "- [s2] B",
        "  - evidence: Data",
        "- [s3] C",
      ].join("\n")
      const entries = parseOutline(md)
      const states = resolveStates(entries)
      expect(states.get(0)).toBe("done")
      expect(states.get(1)).toBe("active")
      expect(states.get(2)).toBe("skeleton")
    })

    it("marks earlier enriched slides as done", () => {
      const md = [
        "- [s1] A",
        "  - what_to_say: X",
        "- [s2] B",
        "  - what_to_say: Y",
        "- [s3] C",
        "  - what_to_say: Z",
      ].join("\n")
      const entries = parseOutline(md)
      const states = resolveStates(entries)
      expect(states.get(0)).toBe("done")
      expect(states.get(1)).toBe("done")
      expect(states.get(2)).toBe("active")
    })

    it("does not assign states to non-slide entries", () => {
      const md = "## Section\n- [s1] Slide\n  - what_to_say: Hello\nSome prose"
      const entries = parseOutline(md)
      const states = resolveStates(entries)
      // Only the slide entry (index 1) gets a state
      expect(states.has(0)).toBe(false) // section
      expect(states.has(1)).toBe(true)  // slide
      expect(states.has(2)).toBe(false) // prose
      expect(states.get(1)).toBe("active")
    })

    it("handles interleaved sections and slides", () => {
      const md = [
        "## Part 1",
        "- [s1] A",
        "  - what_to_say: Done",
        "## Part 2",
        "- [s2] B",
        "  - evidence: Active",
        "- [s3] C",
      ].join("\n")
      const entries = parseOutline(md)
      const states = resolveStates(entries)
      // entries: [section(0), slide(1), section(2), slide(3), slide(4)]
      expect(states.get(1)).toBe("done")
      expect(states.get(3)).toBe("active")
      expect(states.get(4)).toBe("skeleton")
    })

    it("preserves backward compatibility: single enriched slide is active", () => {
      const entries = parseOutline("- [only] Single\n  - what_to_say: Hello")
      const states = resolveStates(entries)
      expect(states.get(0)).toBe("active")
    })
  })

  describe("getSlideEntries — utility", () => {
    it("extracts only slide entries from mixed array", () => {
      const md = "## Section\n- [s1] Slide\nProse line\n- [s2] Slide2"
      const entries = parseOutline(md)
      const slides = getSlideEntries(entries)
      expect(slides).toHaveLength(2)
      expect(slides[0].slug).toBe("s1")
      expect(slides[1].slug).toBe("s2")
    })

    it("returns empty array when no slides exist", () => {
      const md = "## Section\nJust prose"
      const entries = parseOutline(md)
      const slides = getSlideEntries(entries)
      expect(slides).toHaveLength(0)
    })
  })

  describe("backward compatibility — old OutlineSlide[] consumers", () => {
    it("slide entries have all fields expected by legacy consumers", () => {
      const md = "- [intro] Welcome\n  - what_to_say: Hello\n  - evidence: Data"
      const entries = parseOutline(md)
      const slides = getSlideEntries(entries)
      const slide = slides[0]
      // Legacy interface fields
      expect(slide).toHaveProperty("slug")
      expect(slide).toHaveProperty("message")
      expect(slide).toHaveProperty("subItems")
      expect(slide.subItems[0]).toHaveProperty("key")
      expect(slide.subItems[0]).toHaveProperty("value")
    })
  })
})
