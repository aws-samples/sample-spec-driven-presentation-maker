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
