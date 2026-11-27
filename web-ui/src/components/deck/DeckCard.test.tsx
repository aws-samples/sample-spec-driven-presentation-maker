// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { DeckCard } from "./DeckCard"
import type { DeckSummary } from "@/services/deckService"

afterEach(cleanup)

const deck = { deckId: "d1", name: "Quarterly review", slideCount: 4 } as DeckSummary

describe("DeckCard selection", () => {
  it("opens on click when not selecting and has no checkbox unless selectable", () => {
    const onOpen = vi.fn()
    renderWithIntl(<DeckCard deck={deck} index={0} onOpen={onOpen} />)
    expect(screen.queryByRole("checkbox")).toBeNull()
    fireEvent.click(screen.getByText("Quarterly review"))
    expect(onOpen).toHaveBeenCalledWith("d1")
  })

  it("checkbox toggles without opening; shift is forwarded", () => {
    const onOpen = vi.fn(), onSelectToggle = vi.fn()
    renderWithIntl(<DeckCard deck={deck} index={0} onOpen={onOpen} selectable onSelectToggle={onSelectToggle} />)
    const box = screen.getByRole("checkbox", { name: "Select Quarterly review" })
    fireEvent.click(box, { shiftKey: true })
    expect(onSelectToggle).toHaveBeenCalledWith("d1", true)
    expect(onOpen).not.toHaveBeenCalled()
    // Outside selection mode the card body still opens the deck.
    fireEvent.click(screen.getByText("Quarterly review"))
    expect(onOpen).toHaveBeenCalledWith("d1")
  })

  it("in selection mode the whole card toggles (click, Enter, Space) and the menu is hidden", () => {
    const onOpen = vi.fn(), onSelectToggle = vi.fn()
    renderWithIntl(
      <DeckCard deck={deck} index={0} onOpen={onOpen} onDelete={() => {}} selectable selectionMode selected onSelectToggle={onSelectToggle} />,
    )
    expect(screen.queryByLabelText("Deck actions")).toBeNull()
    const card = screen.getByRole("button", { pressed: true })
    fireEvent.click(card)
    fireEvent.keyDown(card, { key: "Enter" })
    fireEvent.keyDown(card, { key: " " })
    expect(onSelectToggle).toHaveBeenCalledTimes(3)
    expect(onOpen).not.toHaveBeenCalled()
    expect(screen.getByRole("checkbox").getAttribute("aria-checked")).toBe("true")
  })
})

describe("DeckCard thumbnail", () => {
  it("renders an HTML deck thumbnail in a sandbox=\"\" iframe", () => {
    const html = { ...deck, thumbnailUrl: "https://b.s3.ap-northeast-1.amazonaws.com/html/d1/preview/intro_1.html?X-Amz-Signature=x" }
    const { container } = renderWithIntl(<DeckCard deck={html} index={0} onOpen={() => {}} />)
    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("iframe")?.getAttribute("sandbox")).toBe("")
    expect(screen.getByRole("img", { name: "Preview of Quarterly review" })).toBeTruthy()
  })

  it("keeps <img> for image thumbnails", () => {
    const png = { ...deck, thumbnailUrl: "/api/preview/d1/preview/intro.png" }
    const { container } = renderWithIntl(<DeckCard deck={png} index={0} onOpen={() => {}} />)
    expect(container.querySelector("iframe")).toBeNull()
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/api/preview/d1/preview/intro.png")
  })
})

describe("DeckCard PPTX download", () => {
  const WITH = "Download PPTX (with speaker notes): Quarterly review"
  const WITHOUT = "Download PPTX (without speaker notes): Quarterly review"

  function openMenu() {
    fireEvent.keyDown(screen.getByLabelText("Deck actions"), { key: "Enter" })
    return { withNotes: screen.getByRole("menuitem", { name: WITH }), withoutNotes: screen.getByRole("menuitem", { name: WITHOUT }) }
  }

  it.each([
    ["with notes", WITH, true],
    ["without notes", WITHOUT, false],
  ])("downloads %s from the menu (keyboard) when the deck has a PPTX", (_label, name, withNotes) => {
    const onDownload = vi.fn(), onOpen = vi.fn()
    renderWithIntl(<DeckCard deck={{ ...deck, hasPptx: true, speakerNotes: "pptx" }} index={0} onOpen={onOpen} onDownload={onDownload} />)
    const items = openMenu()
    expect(items.withNotes.getAttribute("aria-disabled")).toBeNull()
    expect(items.withoutNotes.getAttribute("aria-disabled")).toBeNull()
    expect(items.withNotes.textContent).toBe("Download PPTX (with speaker notes)")
    expect(items.withoutNotes.textContent).toBe("Download PPTX (without speaker notes)")
    fireEvent.click(screen.getByRole("menuitem", { name }))
    expect(onDownload).toHaveBeenCalledWith("d1", withNotes)
    expect(onOpen).not.toHaveBeenCalled()
  })

  it("shows both items for a deck without speakerNotes (an older API, or no notes at all)", () => {
    const onDownload = vi.fn()
    renderWithIntl(<DeckCard deck={{ ...deck, hasPptx: true }} index={0} onOpen={() => {}} onDownload={onDownload} />)
    const items = openMenu()
    expect(items.withNotes.getAttribute("aria-disabled")).toBeNull()
    expect(items.withoutNotes.getAttribute("aria-disabled")).toBeNull()
  })

  it("disables only \"with notes\" when the notes were built to Markdown", () => {
    const onDownload = vi.fn()
    renderWithIntl(<DeckCard deck={{ ...deck, hasPptx: true, speakerNotes: "markdown" }} index={0} onOpen={() => {}} onDownload={onDownload} />)
    const items = openMenu()
    expect(items.withNotes.getAttribute("aria-disabled")).toBe("true")
    expect(items.withoutNotes.getAttribute("aria-disabled")).toBeNull()
    fireEvent.click(items.withNotes)
    expect(onDownload).not.toHaveBeenCalled()
    fireEvent.click(items.withoutNotes)
    expect(onDownload).toHaveBeenCalledWith("d1", false)
  })

  it.each([
    ["no PPTX built yet", { hasPptx: false }],
    ["an HTML deck or an older API (no hasPptx)", {}],
  ])("disables both for %s", (_label, extra) => {
    const onDownload = vi.fn()
    renderWithIntl(<DeckCard deck={{ ...deck, ...extra }} index={0} onOpen={() => {}} onDownload={onDownload} />)
    const items = openMenu()
    expect(items.withNotes.getAttribute("aria-disabled")).toBe("true")
    expect(items.withoutNotes.getAttribute("aria-disabled")).toBe("true")
    fireEvent.click(items.withNotes)
    fireEvent.click(items.withoutNotes)
    expect(onDownload).not.toHaveBeenCalled()
  })
})
