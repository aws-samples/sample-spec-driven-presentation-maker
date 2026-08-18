// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * BriefDocumentView tests — editorial markdown rendering, requirement chips,
 * materials table, HEX swatches, and approval status derivation.
 */

import { describe, it, expect, afterEach } from "vitest"
import { screen, cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { BriefDocumentView } from "./BriefDocumentView"

afterEach(cleanup)

describe("BriefDocumentView", () => {
  describe("arbitrary markdown rendering", () => {
    it("renders headings with editorial typography", () => {
      const md = "# Main Title\n\n## Section\n\nSome text."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const h1 = screen.getByRole("heading", { level: 1 })
      expect(h1.textContent).toContain("Main Title")
      const h2 = screen.getByRole("heading", { level: 2 })
      expect(h2.textContent).toContain("Section")
      expect(screen.getByText("Some text.")).toBeTruthy()
    })

    it("renders tables with proper structure", () => {
      const md = "| Name | Value |\n| --- | --- |\n| A | 1 |\n| B | 2 |"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(screen.getByRole("table")).toBeTruthy()
      expect(screen.getByText("Name")).toBeTruthy()
      expect(screen.getByText("A")).toBeTruthy()
      expect(screen.getByText("B")).toBeTruthy()
    })

    it("renders lists", () => {
      const md = "- Item one\n- Item two\n- Item three"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const items = screen.getAllByRole("listitem")
      expect(items.length).toBe(3)
    })

    it("renders blockquotes", () => {
      const md = "> This is a quote"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const bq = screen.getByRole("blockquote")
      expect(bq.textContent).toContain("This is a quote")
    })

    it("gracefully handles empty content", () => {
      renderWithIntl(<BriefDocumentView content="" outlineExists={false} />)
      // Should render without errors — the document header is still visible
      expect(screen.getByText("specs/brief.md")).toBeTruthy()
    })
  })

  describe("requirement chips", () => {
    it("renders [MUST] as a filled chip", () => {
      const md = "You [MUST] include a title slide."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const chip = screen.getByRole("img", { name: "MUST" })
      expect(chip).toBeTruthy()
      expect(chip.className).toContain("bg-foreground/90")
      expect(chip.className).not.toContain("line-through")
    })

    it("renders [MUST NOT] as an outlined chip with a readable split rule", () => {
      const md = "You [MUST NOT] use Comic Sans."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const chip = screen.getByRole("img", { name: "MUST NOT" })
      expect(chip).toBeTruthy()
      expect(chip.className).toContain("requirement-must-not")
      expect(chip.className).toContain("border-foreground/60")
      expect(chip.className).not.toContain("line-through")
      expect(chip.className).not.toContain("bg-foreground/90")
    })

    it("renders [PREFER] as a dashed-border chip", () => {
      const md = "[PREFER] serif fonts for headings."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const chip = screen.getByRole("img", { name: "PREFER" })
      expect(chip).toBeTruthy()
      expect(chip.className).toContain("border-dashed")
    })

    it("renders multiple chips in same paragraph", () => {
      const md = "[MUST] include logo. [MUST NOT] exceed 20 slides. [PREFER] dark theme."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(screen.getByRole("img", { name: "MUST" })).toBeTruthy()
      expect(screen.getByRole("img", { name: "MUST NOT" })).toBeTruthy()
      expect(screen.getByRole("img", { name: "PREFER" })).toBeTruthy()
    })

    it("leaves unrecognized bracket markers as plain text", () => {
      const md = "Use [OTHER] format."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(screen.queryByRole("img")).toBeNull()
      // The text contains the literal "[OTHER]" - verify no chips rendered
      const { container } = renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(container.textContent).toContain("[OTHER]")
    })
  })

  describe("HEX color swatches", () => {
    it("renders inline color swatches for HEX codes in text", () => {
      const md = "Primary color is #FF5500 and secondary is #00AAFF."
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const swatches = screen.getAllByLabelText(/^Color #/)
      expect(swatches.length).toBe(2)
    })

    it("renders swatches for 3-digit HEX in table cells", () => {
      const md = "| Color | Hex |\n| --- | --- |\n| Red | #F00 |"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(screen.getByLabelText("Color #F00")).toBeTruthy()
    })
  })

  describe("materials table styling", () => {
    it("applies materials class when header contains 'Material'", () => {
      const md = "| Material | Color | Usage |\n| --- | --- | --- |\n| Paper | #FFFFFF | Background |"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const table = screen.getByRole("table")
      expect(table.className).toContain("brief-materials-table")
    })

    it("does not apply materials class for generic tables", () => {
      const md = "| Name | Value |\n| --- | --- |\n| A | 1 |"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const table = screen.getByRole("table")
      expect(table.className).not.toContain("brief-materials-table")
    })
  })

  describe("approval status derivation", () => {
    it("shows pending when outlineExists is false", () => {
      const md = "# Brief"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const status = screen.getByRole("status")
      expect(status.textContent).toContain("Pending approval")
    })

    it("shows approved when outlineExists is true", () => {
      const md = "# Brief"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={true} />)
      const status = screen.getByRole("status")
      expect(status.textContent).toContain("Approved")
    })

    it("has correct aria-label for approved state", () => {
      const md = "# Brief"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={true} />)
      expect(screen.getByLabelText("Brief has been approved — outline exists")).toBeTruthy()
    })

    it("has correct aria-label for pending state", () => {
      const md = "# Brief"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(screen.getByLabelText("Brief is pending approval — no outline yet")).toBeTruthy()
    })
  })

  describe("document-surface scope", () => {
    it("wraps content in document-surface class for Fraunces headings", () => {
      const md = "# Title"
      const { container } = renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      const article = container.querySelector("article.document-surface")
      expect(article).toBeTruthy()
    })

    it("shows the specs/brief.md file path", () => {
      const md = "# Some Brief"
      renderWithIntl(<BriefDocumentView content={md} outlineExists={false} />)
      expect(screen.getByText("specs/brief.md")).toBeTruthy()
    })
  })
})
