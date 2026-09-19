// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { OutlineView } from "./OutlineView"

beforeEach(() => localStorage.clear())
afterEach(() => {
  cleanup()
  localStorage.clear()
})

const storyboard = [
  "# Product strategy",
  "Introductory context.",
  "## Opening",
  "- [welcome] Welcome to the presentation",
  "  - body: The full opening message",
  "  - visual: Hero image with #123456 background",
  "  - evidence: Customer study",
  "- [agenda] Today’s agenda",
  "## Decision",
  "- [recommendation] Choose the focused option",
  "  - body: First supporting point.",
  "  - body: Second supporting point.",
  "  - visual: [TBD: comparison chart]",
  "  - evidence: Decision memo",
].join("\n")

describe("OutlineView", () => {
  describe("empty state", () => {
    it.each([null, "", "\n\n\n"])("shows the empty state for empty content", (content) => {
      renderWithIntl(<OutlineView content={content} />)
      expect(screen.getByText(/outline will appear/i)).toBeTruthy()
    })
  })

  it("renders the deck title and translated document counts", () => {
    renderWithIntl(<OutlineView content={storyboard} />)

    expect(screen.getByRole("heading", { level: 1, name: "Product strategy" })).toBeTruthy()
    expect(screen.getByText(/3 slides/)).toBeTruthy()
    expect(screen.getByText(/2 chapters/)).toBeTruthy()
    expect(screen.queryByText("# Product strategy")).toBeNull()
  })

  it("renders chapter indices, headings, slide counts, and rules", () => {
    const { container } = renderWithIntl(<OutlineView content={storyboard} />)
    const chapters = container.querySelectorAll("[data-entry-type='section']")

    expect(chapters).toHaveLength(2)
    expect(chapters[0].querySelector(".storyboard-chapter-number")?.textContent).toBe("01")
    expect(chapters[1].querySelector(".storyboard-chapter-number")?.textContent).toBe("02")
    expect(screen.getByRole("heading", { level: 2, name: "Opening" })).toBeTruthy()
    expect(screen.getByRole("heading", { level: 2, name: "Decision" })).toBeTruthy()
    expect(chapters[0].textContent).toContain("2 slides")
    expect(chapters[1].textContent).toContain("1 slide")
    expect(container.querySelectorAll(".storyboard-chapter-rule")).toHaveLength(2)
  })

  it("renders slides in source order with sequential number badges", () => {
    const { container } = renderWithIntl(<OutlineView content={storyboard} />)
    const slides = [...container.querySelectorAll<HTMLElement>("[data-slide-slug]")]

    expect(slides.map((slide) => slide.dataset.slideSlug)).toEqual([
      "welcome",
      "agenda",
      "recommendation",
    ])
    expect(slides.map((slide) => slide.querySelector(".storyboard-slide-number")?.textContent)).toEqual([
      "1",
      "2",
      "3",
    ])
  })

  it("shows the title, complete body, visual, and evidence", () => {
    renderWithIntl(<OutlineView content={storyboard} />)

    expect(screen.getByRole("heading", { level: 3, name: "Welcome to the presentation" })).toBeTruthy()
    expect(screen.getByText("The full opening message")).toBeTruthy()
    expect(screen.getByText("First supporting point. Second supporting point.")).toBeTruthy()
    expect(screen.getAllByText("VISUAL")).toHaveLength(2)
    expect(screen.getAllByText("SRC")).toHaveLength(2)
    expect(screen.getByText(/Hero image with/)).toBeTruthy()
    expect(screen.getByText("Customer study")).toBeTruthy()
  })

  it("uses the same paper card for a skeleton without rendering a footer", () => {
    const { container } = renderWithIntl(<OutlineView content={storyboard} />)
    const skeleton = container.querySelector<HTMLElement>("[data-slide-slug='agenda']")

    expect(skeleton?.dataset.state).toBe("skeleton")
    expect(skeleton?.querySelector(".storyboard-paper")).toBeTruthy()
    expect(skeleton?.querySelector(".storyboard-footer")).toBeNull()
    expect(skeleton?.querySelector(".border-dashed")).toBeNull()
  })

  it("renders TBD detail as an outlined mono chip", () => {
    const { container } = renderWithIntl(<OutlineView content={storyboard} />)
    const chip = screen.getByText("TBD: comparison chart")

    expect(chip.className).toContain("storyboard-tbd")
    expect(container.querySelectorAll(".storyboard-tbd")).toHaveLength(1)
  })

  it("retains active, done, and skeleton state semantics", () => {
    const { container } = renderWithIntl(<OutlineView content={storyboard} />)

    expect(container.querySelectorAll("[data-state='done']")).toHaveLength(1)
    expect(container.querySelectorAll("[data-state='active']")).toHaveLength(1)
    expect(container.querySelectorAll("[data-state='skeleton']")).toHaveLength(1)
    expect(
      container.querySelector("[data-state='active'] .storyboard-slide-number")?.getAttribute("data-active")
    ).toBe("true")
  })

  it("switches layout classes and persists the selected layout", async () => {
    const firstRender = renderWithIntl(<OutlineView content={storyboard} />)
    const view = firstRender.container.querySelector(".storyboard-view")

    expect(view?.className).toContain("storyboard-layout-grid")
    fireEvent.click(screen.getByRole("button", { name: "Column" }))
    expect(view?.className).toContain("storyboard-layout-column")
    expect(localStorage.getItem("sdpm-outline-layout")).toBe("column")

    firstRender.unmount()
    const secondRender = renderWithIntl(<OutlineView content={storyboard} />)
    await waitFor(() => {
      expect(secondRender.container.querySelector(".storyboard-view")?.className).toContain(
        "storyboard-layout-column"
      )
    })
    expect(screen.getByRole("button", { name: "Column" }).getAttribute("aria-pressed")).toBe("true")
  })

  it("renders non-title prose entries as muted prose blocks", () => {
    const { container } = renderWithIntl(<OutlineView content={storyboard} />)

    expect(screen.getByText("Introductory context.")).toBeTruthy()
    expect(container.querySelectorAll("[data-entry-type='prose']")).toHaveLength(1)
    expect(container.querySelector(".storyboard-prose")?.textContent).toBe("Introductory context.")
  })
})
