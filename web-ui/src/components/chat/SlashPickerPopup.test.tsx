// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { PickerItem } from "@/lib/slashToken"
import { SlashPickerPopup, type SlashPickerPopupProps } from "./SlashPickerPopup"

vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))

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
  it("renders non-empty sections in template then style order", () => {
    renderPopup()

    const templateHeading = screen.getByText("Template")
    const styleHeading = screen.getByText("Style")
    expect(templateHeading.compareDocumentPosition(styleHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole("listbox", { name: "Template and style suggestions" }).id).toBe("slash-listbox")
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
})
