// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * OutlineView tests — light table / detail view rendering, section/prose display,
 * slide card content, state frames, auto-scroll, and empty state.
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
      // Whitespace content may render as prose (not discarded) — 
      // this is the "nothing invented, nothing discarded" principle.
      const { container } = renderWithIntl(<OutlineView content={"\n\n\n"} />)
      // It should not throw and should render something
      expect(container.firstChild).toBeTruthy()
    })
  })

  describe("light table mode (all slides skeleton)", () => {
    const skeletonMd = [
      "## Introduction",
      "- [cover] Cover slide",
      "- [agenda] Agenda",
      "- [overview] Product overview",
    ].join("\n")

    it("renders a 3-column grid", () => {
      const { container } = renderWithIntl(<OutlineView content={skeletonMd} />)
      const grid = container.querySelector("[data-view='light-table']")
      expect(grid).toBeTruthy()
    })

    it("renders section headings full-width", () => {
      const { container } = renderWithIntl(<OutlineView content={skeletonMd} />)
      const section = container.querySelector("[data-entry-type='section']")
      expect(section).toBeTruthy()
      expect(section?.classList.contains("col-span-full")).toBe(true)
    })

    it("renders all slide cards with dashed borders (skeleton state)", () => {
      const { container } = renderWithIntl(<OutlineView content={skeletonMd} />)
      const cards = container.querySelectorAll("[data-state='skeleton']")
      expect(cards.length).toBe(3)
    })

    it("displays slide messages", () => {
      renderWithIntl(<OutlineView content={skeletonMd} />)
      expect(screen.getByText("Cover slide")).toBeTruthy()
      expect(screen.getByText("Agenda")).toBeTruthy()
      expect(screen.getByText("Product overview")).toBeTruthy()
    })

    it("displays slide slugs", () => {
      renderWithIntl(<OutlineView content={skeletonMd} />)
      expect(screen.getByText("cover")).toBeTruthy()
      expect(screen.getByText("agenda")).toBeTruthy()
    })
  })

  describe("detail mode (enriched slides)", () => {
    const enrichedMd = [
      "## Opening",
      "- [intro] Welcome to our presentation",
      "  - what_to_say: Thank you for being here today",
      "  - evidence: Survey results from Q3",
      "  - what_to_show: Bar chart comparing quarters",
      "  - notes: Pause after the chart reveal",
      "- [next-steps] What comes next",
    ].join("\n")

    it("renders full-width layout (no 3-col grid)", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      const grid = container.querySelector("[data-view='light-table']")
      expect(grid).toBeNull()
    })

    it("renders the what_to_say as a blockquote lead", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      const bq = screen.getByText(/Thank you for being here today/i)
      expect(bq.closest("blockquote")).toBeTruthy()
    })

    it("renders Evidence on the slide face", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("Evidence")).toBeTruthy()
      expect(screen.getByText(/Survey results from Q3/)).toBeTruthy()
    })

    it("renders Visual on the slide face", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("Visual")).toBeTruthy()
      expect(screen.getByText(/Bar chart comparing quarters/)).toBeTruthy()
    })

    it("renders notes as a separate band below the slide", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("Notes")).toBeTruthy()
      expect(screen.getByText(/Pause after the chart reveal/)).toBeTruthy()
    })

    it("renders slide number and slug as page chrome", () => {
      renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(screen.getByText("intro")).toBeTruthy()
      // Slide number 1
      expect(screen.getByText("1")).toBeTruthy()
    })

    it("marks the last enriched slide as active", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      const activeCard = container.querySelector("[data-state='active']")
      expect(activeCard).toBeTruthy()
      expect(activeCard?.getAttribute("data-slide-slug")).toBe("intro")
    })

    it("marks skeleton slides without sub-items", () => {
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      const skeletonCards = container.querySelectorAll("[data-state='skeleton']")
      expect(skeletonCards.length).toBe(1) // next-steps
    })
  })

  describe("section and prose rendering in detail mode", () => {
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
      const tbd = container.querySelector("[class*='border-dashed']")
      expect(tbd).toBeTruthy()
      expect(tbd?.textContent).toContain("TBD")
      // Should NOT have amber/brand-amber styling
      expect(tbd?.className).not.toContain("brand-amber")
    })

    it("renders [TBD: detail] with detail text", () => {
      const md = "- [s1] Slide\n  - what_to_show: [TBD: need screenshot]"
      renderWithIntl(<OutlineView content={md} />)
      expect(screen.getByText(/TBD: need screenshot/)).toBeTruthy()
    })
  })

  describe("frame states", () => {
    it("skeleton slides have dashed border", () => {
      const md = "- [s1] A\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const cards = container.querySelectorAll("[data-state='skeleton']")
      expect(cards.length).toBe(2)
    })

    it("active slide has solid border with shadow", () => {
      const md = "- [s1] A\n  - what_to_say: X"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const active = container.querySelector("[data-state='active']")
      expect(active).toBeTruthy()
    })

    it("done slides have quiet solid border", () => {
      const md = "- [s1] A\n  - what_to_say: X\n- [s2] B\n  - what_to_say: Y"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      const done = container.querySelectorAll("[data-state='done']")
      expect(done.length).toBe(1)
    })
  })

  describe("document surface class", () => {
    it("applies document-surface class for Fraunces headings", () => {
      const md = "- [s1] A\n  - what_to_say: Text"
      const { container } = renderWithIntl(<OutlineView content={md} />)
      expect(container.querySelector(".document-surface")).toBeTruthy()
    })
  })

  describe("automatic view switching", () => {
    it("uses light table for all-skeleton and detail for enriched", () => {
      // All skeleton => light table
      const skeletonMd = "- [s1] A\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={skeletonMd} />)
      expect(container.querySelector("[data-view='light-table']")).toBeTruthy()
    })

    it("uses detail mode when any slide has sub-items", () => {
      const enrichedMd = "- [s1] A\n  - what_to_say: Hello\n- [s2] B"
      const { container } = renderWithIntl(<OutlineView content={enrichedMd} />)
      expect(container.querySelector("[data-view='light-table']")).toBeNull()
    })
  })
})
