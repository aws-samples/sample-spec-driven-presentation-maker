// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * TemplatePickerSection tests — rendering, ordering, current-template
 * indication, and selection callback arguments.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { screen, waitFor, fireEvent, cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { TemplatePickerSection } from "./TemplatePickerSection"
import type { TemplateEntry } from "@/services/deckService"

vi.mock("@/services/deckService", () => ({
  fetchTemplates: vi.fn(),
}))

import { fetchTemplates } from "@/services/deckService"

const TEMPLATES: TemplateEntry[] = [
  {
    name: "builtin-a",
    source: "builtin",
    description: "Builtin A",
    theme_colors: { background: "#ffffff", text: "#111111", accent1: "#ff0000" },
    fonts: { halfwidth: "Arial", fullwidth: null },
    layout_count: 10,
  },
  {
    name: "my-brand",
    source: "user",
    description: "Company brand",
    theme_colors: { background: "#001122", text: "#eeeeee" },
    fonts: {},
    layout_count: 5,
  },
  {
    name: "corporate",
    source: "builtin",
    description: "",
    theme_colors: {},
    fonts: {},
    layout_count: 8,
  },
]

describe("TemplatePickerSection", () => {
  beforeEach(() => {
    vi.mocked(fetchTemplates).mockResolvedValue(TEMPLATES)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("renders all templates after loading", async () => {
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate={null} onTemplateSelect={() => {}} />
    )
    expect(await screen.findByText("my-brand")).toBeTruthy()
    expect(screen.getByText("builtin-a")).toBeTruthy()
    expect(screen.getByText("corporate")).toBeTruthy()
    expect(screen.getByText("Template")).toBeTruthy()
  })

  it("shows descriptions on cards without requiring hover", async () => {
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate={null} onTemplateSelect={() => {}} />
    )
    await screen.findByText("my-brand")
    // Descriptions (including per-user builtin notes) are rendered as visible text
    expect(screen.getByText("Builtin A")).toBeTruthy()
    expect(screen.getByText("Company brand")).toBeTruthy()
    // Templates without a description render no empty paragraph
    const corporateCard = screen.getByRole("button", { name: "Use the corporate template" })
    expect(corporateCard.querySelector("p")).toBeNull()
  })

  it("orders user templates before builtin when nothing is confirmed", async () => {
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate={null} onTemplateSelect={() => {}} />
    )
    await screen.findByText("my-brand")
    const cards = screen.getAllByRole("button")
    const names = cards.map((c) => c.getAttribute("aria-label"))
    expect(names).toEqual([
      "Use the my-brand template",
      "Use the builtin-a template",
      "Use the corporate template",
    ])
  })

  it("marks the confirmed template with data-current without reordering", async () => {
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate="corporate.pptx" onTemplateSelect={() => {}} />
    )
    await screen.findByText("my-brand")
    await waitFor(() => {
      const card = screen.getByRole("button", { name: "Use the corporate template" })
      expect(card.getAttribute("data-current")).toBe("true")
    })
    // Order stays user → builtin — the current card does NOT jump to the front
    const names = screen.getAllByRole("button").map((c) => c.getAttribute("aria-label"))
    expect(names).toEqual([
      "Use the my-brand template",
      "Use the builtin-a template",
      "Use the corporate template",
    ])
    // Header shows the labelled current template name
    expect(screen.getByText("In use: corporate")).toBeTruthy()
  })

  it("normalizes template values with directory prefixes", async () => {
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate="templates/my-brand.pptx" onTemplateSelect={() => {}} />
    )
    await screen.findByText("builtin-a")
    expect(
      screen.getByRole("button", { name: "Use the my-brand template" }).getAttribute("data-current")
    ).toBe("true")
    expect(screen.getByText("In use: my-brand")).toBeTruthy()
  })

  it("calls onTemplateSelect with isChange=false when unconfirmed", async () => {
    const onSelect = vi.fn()
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate={null} onTemplateSelect={onSelect} />
    )
    await screen.findByText("my-brand")
    fireEvent.click(screen.getByRole("button", { name: "Use the my-brand template" }))
    expect(onSelect).toHaveBeenCalledWith("my-brand", false)
  })

  it("calls onTemplateSelect with isChange=true when a template is confirmed", async () => {
    const onSelect = vi.fn()
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate="corporate.pptx" onTemplateSelect={onSelect} />
    )
    await screen.findByText("my-brand")
    // The current card is NOT disabled — re-asserting the same template is allowed
    fireEvent.click(screen.getByRole("button", { name: "Use the corporate template" }))
    expect(onSelect).toHaveBeenCalledWith("corporate", true)
  })

  it("shows the custom badge only for user templates", async () => {
    renderWithIntl(
      <TemplatePickerSection idToken="tok" currentTemplate={null} onTemplateSelect={() => {}} />
    )
    await screen.findByText("my-brand")
    expect(screen.getAllByText("Custom")).toHaveLength(1)
  })
})
