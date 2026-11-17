// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen, within } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { FORMAT_HTML_ITEM, type PickerItem } from "@/lib/slashToken"
import { SlashPickerPopup, placeSlashPanel, type SlashPickerPopupProps } from "./SlashPickerPopup"

const items: PickerItem[] = [
  {
    kind: "template",
    name: "corporate",
    description: "A structured business template",
    source: "builtin",
    pinned: false,
    themeColors: { background: "#ffffff", text: "#111111", accent1: "#ff9900" },
    fonts: { halfwidth: "Arial", fullwidth: "Noto Sans JP" },
  },
  {
    kind: "style",
    name: "my-style",
    description: "A custom editorial style",
    source: "user",
    pinned: true,
  },
]

function renderPopup(overrides: Partial<SlashPickerPopupProps> = {}) {
  const textarea = document.createElement("textarea")
  document.body.appendChild(textarea)
  const props: SlashPickerPopupProps = {
    open: true,
    query: "",
    items,
    filtered: items,
    activeIndex: 0,
    onActiveIndexChange: vi.fn(),
    onSelect: vi.fn(),
    loading: false,
    textareaRef: { current: textarea },
    listboxId: "slash-listbox",
    ...overrides,
  }
  return { ...renderWithIntl(<SlashPickerPopup {...props} />), props, textarea }
}

afterEach(() => {
  cleanup()
  document.body.querySelectorAll("textarea").forEach((textarea) => textarea.remove())
})

describe("SlashPickerPopup", () => {
  it("renders the Format section last with the localized HTML option", () => {
    const all = [...items, FORMAT_HTML_ITEM]
    const onSelect = vi.fn()
    renderPopup({ items: all, filtered: all, activeIndex: 2, onSelect })

    const styleHeading = screen.getByText("Style")
    const formatHeading = screen.getByText("Format")
    expect(styleHeading.compareDocumentPosition(formatHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const option = screen.getByRole("option", { name: /HTML/ })
    expect(option.textContent).toContain("Present in a browser. Can't be edited in PowerPoint.")
    fireEvent.click(option)
    expect(onSelect).toHaveBeenCalledWith(FORMAT_HTML_ITEM)
  })

  it("renders non-empty sections in template then style order", () => {
    renderPopup()

    const templateHeading = screen.getByText("Template")
    const styleHeading = screen.getByText("Style")
    expect(templateHeading.compareDocumentPosition(styleHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole("listbox", { name: "Template, style and format suggestions" }).id).toBe("slash-listbox")
  })

  it("hides an empty section and marks custom items", () => {
    renderPopup({ filtered: [items[1]], activeIndex: 0 })

    expect(screen.queryByText("Template")).toBeNull()
    expect(screen.getByText("Style")).toBeTruthy()
    expect(screen.getByText("Custom")).toBeTruthy()
  })

  it("exposes active options and selects a clicked row", () => {
    const onSelect = vi.fn()
    renderPopup({ activeIndex: 1, onSelect })

    expect(screen.getByRole("option", { name: /corporate/ }).getAttribute("aria-selected")).toBe("false")
    const selected = screen.getByRole("option", { name: /my-style/ })
    expect(selected.getAttribute("aria-selected")).toBe("true")
    expect(selected.id).toBe("slash-listbox-opt-1")

    fireEvent.mouseDown(selected)
    fireEvent.click(selected)
    expect(onSelect).toHaveBeenCalledWith(items[1])
  })

  it("moves highlight only when the pointer moves", () => {
    const onActiveIndexChange = vi.fn()
    renderPopup({ onActiveIndexChange })

    fireEvent.mouseMove(screen.getByRole("option", { name: /my-style/ }))
    expect(onActiveIndexChange).toHaveBeenCalledWith(1, "mouse")
  })

  it("shows loading instead of candidates", () => {
    renderPopup({ loading: true })

    expect(screen.getByText("Loading…")).toBeTruthy()
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("shows the no-match row when filtering returns nothing", () => {
    renderPopup({ filtered: [] })

    expect(screen.getByText("No matches")).toBeTruthy()
    expect(screen.queryByText("Template")).toBeNull()
    expect(screen.queryByText("Style")).toBeNull()
  })

  it("does not render when closed", () => {
    renderPopup({ open: false })

    expect(screen.queryByRole("listbox")).toBeNull()
  })

  it("narrows by kind through the kind buttons without taking focus", () => {
    const onKindChange = vi.fn()
    renderPopup({ onKindChange, query: "style lu" })

    const group = screen.getByRole("group", { name: "Show" })
    const style = within(group).getByRole("button", { name: "Style" })
    expect(style.getAttribute("aria-pressed")).toBe("true")
    expect(within(group).getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("false")
    expect(screen.getByText("lu")).toBeTruthy()

    const all = within(group).getByRole("button", { name: "All" })
    expect(fireEvent.mouseDown(all)).toBe(false)
    fireEvent.click(all)
    expect(onKindChange).toHaveBeenCalledWith(null)
  })

  describe("placement", () => {
    const rect = (left: number, top: number, width: number, height: number) => ({ left, top, width, right: left + width, bottom: top + height })

    it("is as wide as the window allows, not as wide as the input", () => {
      // 1440 x 900 window, chat panel at the right edge: input frame 416px wide from x=1008.
      const p = placeSlashPanel(rect(1008, 780, 416, 100), 1440, 900)
      expect(p.width).toBe(640)
      // Ends at the input's right edge and opens leftwards over the deck.
      expect(p.left + p.width).toBe(1424)
      expect(p.bottom).toBe(900 - 780 + 8)
      expect(p.maxHeight).toBe(480)
    })

    it("centres on a wide input", () => {
      const p = placeSlashPanel(rect(360, 700, 720, 120), 1440, 900)
      expect(p.left).toBe(360 + 360 - 320)
    })

    it("opens below when there is little room above and more below", () => {
      const p = placeSlashPanel(rect(360, 200, 720, 120), 1440, 900)
      expect(p.top).toBe(328)
      expect(p.bottom).toBeUndefined()
      expect(p.maxHeight).toBe(480)
    })

    it("stays inside a narrow window", () => {
      const p = placeSlashPanel(rect(8, 600, 384, 80), 400, 800)
      expect(p.left).toBe(12)
      expect(p.width).toBe(376)
    })
  })
})
