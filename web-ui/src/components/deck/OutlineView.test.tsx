// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * OutlineView v5 tests — slide narrative layout:
 * number rail + card, skeleton/enriched structure, spec sheet,
 * section/prose display, state frames, auto-scroll, empty state.
 * No light-table mode, no clipping structures.
 */

import { describe, it, expect, afterEach } from "vitest"
import { screen, cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { OutlineView } from "./OutlineView"

afterEach(cleanup)

describe("OutlineView", () => {
  describe("empty state", () => {
    it("shows empty state for null content", () => {
      renderWithIntl(<OutlineView content={null} />)
      expect(screen.getByText(/outline will appear/i)).toBeTruthy()
    })

    it("shows empty state for empty string", () => {
      renderWithIntl(<OutlineView content="" />)
      expect(screen.getByText(/outline will appear/i)).toBeTruthy()
    })

    it("does not crash on whitespace-only content", () => {
      const { container } = renderWithIntl(<OutlineView content={"\n\n\n"} />)
      expect(container.firstChild).toBeTruthy()
    })
  })

  describe("number rail structure", () => {
    const md = [
      "- [cover] Cover slide",
      "- [agenda] Agenda",
      "- [overview] Product overview",
    ].join("\n")

    it("renders slide entries with number rail grid (36px + 1fr)", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const slideRows = container.querySelectorAll("[data-slide-slug]")
      expect(slideRows.length).toBe(3)
      // Each row uses inline grid-template-columns
      slideRows.forEach((row) => {
        expect((row as HTMLElement).style.gridTemplateColumns).toBe("36px 1fr")
      })
    })

    it("renders sequential slide numbers", () => {
      renderWithIntl(<OutlineView content={md} />)
      expect(screen.getByText("1")).toBeTruthy()
      expect(screen.getByText("2")).toBeTruthy()
      expect(screen.getByText("3")).toBeTruthy()
    })

    it("number rail uses tabular-nums", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const numberSpans = container.querySelectorAll("[data-slide-slug] > span:first-child")
      numberSpans.forEach((span) => {
        expect(span.className).toContain("tabular-nums")
      })
    })

    it("active slide number is inverted (bg-foreground text-background)", () => {
      const md = "- [s1] A\n  - what_to_say: Hello"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const active = container.querySelector("[data-state='active']")
      const numSpan = active?.querySelector(":scope > span:first-child")
      expect(numSpan?.className).toContain("bg-foreground")
      expect(numSpan?.className).toContain("text-background")
    })

    it("skeleton slide numbers are muted (not inverted)", () => {
      const md = "- [s1] A\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const skeleton = container.querySelector("[data-state='skeleton']")
      const numSpan = skeleton?.querySelector(":scope > span:first-child")
      expect(numSpan?.className).not.toContain("bg-foreground")
      expect(numSpan?.className).toContain("text-foreground-secondary")
    })
  })

  describe("skeleton slide (slim dashed card)", () => {
    const md = "- [cover] Cover slide\n- [agenda] Agenda items"

    it("renders with dashed border", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const cards = container.querySelectorAll("[data-state='skeleton']")
      expect(cards.length).toBe(2)
      // Each skeleton card contains a dashed-border div
      cards.forEach((card) => {
        const dashedDiv = card.querySelector(".border-dashed")
        expect(dashedDiv).toBeTruthy()
      })
    })

    it("displays slug as eyebrow in mono font", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const eyebrows = container.querySelectorAll(".font-mono.text-\\[11px\\]")
      expect(eyebrows.length).toBeGreaterThanOrEqual(2)
      expect(eyebrows[0].textContent).toBe("cover")
    })

    it("displays message text", () => {
      renderWithIntl(<OutlineView content={md} />)
      expect(screen.getByText("Cover slide")).toBeTruthy()
      expect(screen.getByText("Agenda items")).toBeTruthy()
    })
  })

  describe("enriched slide (solid border face)", () => {
    const enrichedMd = [
      "## Opening",
      "- [intro] Welcome to our presentation",
      "  - what_to_say: Thank you for being here today",
      "  - evidence: Survey results from Q3",
      "  - what_to_show: Bar chart comparing quarters",
      "  - notes: Pause after the chart reveal",
      "- [next-steps] What comes next",
    ].join("\n")

    it("renders enriched slide with solid border (no dashed)", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      const active = container.querySelector("[data-state='active']")
      expect(active).toBeTruthy()
      // The card inside should have border-solid
      const face = active?.querySelector(".border-solid")
      expect(face).toBeTruthy()
    })

    it("renders accent rule bar", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      const rules = container.querySelectorAll("[aria-hidden='true'].bg-foreground\\/85")
      expect(rules.length).toBeGreaterThanOrEqual(1)
    })

    it("renders what_to_say with curly quotes (not italic, not blockquote)", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      // Should have the quote text
      expect(screen.getByText(/Thank you for being here today/)).toBeTruthy()
      // Should NOT be in a blockquote element
      const quoteEl = screen.getByText(/Thank you for being here today/)
      expect(quoteEl.closest("blockquote")).toBeNull()
      // Should NOT have italic class
      expect(quoteEl.className).not.toContain("italic")
    })

    it("renders spec sheet with Evidence label and content", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("Evidence")).toBeTruthy()
      expect(screen.getByText(/Survey results from Q3/)).toBeTruthy()
    })

    it("renders spec sheet with Visual label and content", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("Visual")).toBeTruthy()
      expect(screen.getByText(/Bar chart comparing quarters/)).toBeTruthy()
    })

    it("spec sheet uses 92px label column grid", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      const specRows = container.querySelectorAll(".grid-cols-\\[92px_1fr\\]")
      expect(specRows.length).toBeGreaterThanOrEqual(2)
    })

    it("renders notes band outside the slide face", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("Notes")).toBeTruthy()
      expect(screen.getByText(/Pause after the chart reveal/)).toBeTruthy()
    })

    it("renders slide number and slug", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("intro")).toBeTruthy()
      expect(screen.getByText("1")).toBeTruthy()
    })
  })

  describe("no clipping structures", () => {
    const md = "- [s1] A long message\n  - what_to_say: Details\n  - evidence: Data"

    it("does not use aspect-ratio forcing", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const allElements = container.querySelectorAll("*")
      allElements.forEach((el) => {
        const style = (el as HTMLElement).style
        expect(style.aspectRatio).toBeFalsy()
      })
    })

    it("does not use overflow-hidden on content areas", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      // The only overflow-y-auto is the outer scroll container
      const overflowHidden = container.querySelectorAll(".overflow-hidden")
      expect(overflowHidden.length).toBe(0)
    })

    it("does not use absolute inset for content", () => {
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const absoluteEls = container.querySelectorAll(".absolute")
      expect(absoluteEls.length).toBe(0)
    })
  })

  describe("section and prose rendering", () => {
    const mixedMd = [
      "This is introductory prose.",
      "## Section One",
      "- [s1] First slide",
      "  - what_to_say: Hello",
      "More prose after the slide.",
      "## Section Two",
      "- [s2] Second slide",
    ].join("\n")

    it("renders prose entries", () => {
      renderWithIntl(<OutlineView content={mixedMd} />)
      expect(screen.getByText("This is introductory prose.")).toBeTruthy()
      expect(screen.getByText("More prose after the slide.")).toBeTruthy()
    })

    it("renders section headings as h2", () => {
      renderWithIntl(<OutlineView content={mixedMd} />)
      const headings = screen.getAllByRole("heading", { level: 2 })
      expect(headings.length).toBe(2)
      expect(headings[0].textContent).toContain("Section One")
      expect(headings[1].textContent).toContain("Section Two")
    })

    it("section entries have data-entry-type=section", () => {
      const { container } = renderWithIntl(<OutlineView content={mixedMd} />)
      const sections = container.querySelectorAll("[data-entry-type='section']")
      expect(sections.length).toBe(2)
    })

    it("prose entries have data-entry-type=prose", () => {
      const { container } = renderWithIntl(<OutlineView content={mixedMd} />)
      const proseBlocks = container.querySelectorAll("[data-entry-type='prose']")
      expect(proseBlocks.length).toBe(2)
    })
  })

  describe("TBD badges", () => {
    it("renders [TBD] as a dashed ink chip (not amber)", () => {
      const md = "- [s1] Slide\n  - evidence: [TBD] data pending"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const tbd = container.querySelector("[class*='border-dashed'][class*='border-foreground']")
      expect(tbd).toBeTruthy()
      expect(tbd?.textContent).toContain("TBD")
      expect(tbd?.className).not.toContain("brand-amber")
    })

    it("renders [TBD: detail] with detail text", () => {
      const md = "- [s1] Slide\n  - what_to_show: [TBD: need screenshot]"
      renderWithIntl(<OutlineView content={md} />)
      expect(screen.getByText(/TBD: need screenshot/)).toBeTruthy()
    })
  })

  describe("frame states", () => {
    it("skeleton slides have data-state=skeleton", () => {
      const md = "- [s1] A\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const cards = container.querySelectorAll("[data-state='skeleton']")
      expect(cards.length).toBe(2)
    })

    it("active slide has data-state=active", () => {
      const md = "- [s1] A\n  - what_to_say: X"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const active = container.querySelector("[data-state='active']")
      expect(active).toBeTruthy()
    })

    it("done slides have data-state=done", () => {
      const md = "- [s1] A\n  - what_to_say: X\n- [s2] B\n  - what_to_say: Y"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const done = container.querySelectorAll("[data-state='done']")
      expect(done.length).toBe(1)
    })
  })

  describe("document surface class", () => {
    it("applies document-surface class for section heading font scoping", () => {
      const md = "- [s1] A\n  - what_to_say: Text"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      expect(container.querySelector(".document-surface")).toBeTruthy()
    })
  })

  describe("no light-table mode (v5: single view)", () => {
    it("uses same single-column layout for all-skeleton slides", () => {
      const skeletonMd = "- [s1] A\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={skeletonMd} />)
      // No light-table grid
      expect(container.querySelector("[data-view='light-table']")).toBeNull()
      // Uses the number-rail grid structure
      const slideRows = container.querySelectorAll("[data-slide-slug]")
      expect(slideRows.length).toBe(2)
    })

    it("uses same layout when any slide has sub-items", () => {
      const enrichedMd = "- [s1] A\n  - what_to_say: Hello\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(container.querySelector("[data-view='light-table']")).toBeNull()
      const slideRows = container.querySelectorAll("[data-slide-slug]")
      expect(slideRows.length).toBe(2)
    })
  })
})
