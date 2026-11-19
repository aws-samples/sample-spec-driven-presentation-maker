// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ChoiceChip } from "./ChoiceChip"
import { setKindToken, tokenName, type PickerItem } from "@/lib/slashToken"

afterEach(cleanup)

const items: PickerItem[] = [
  { kind: "style", name: "aws-dark", description: "Dark console", source: "builtin", pinned: false },
  { kind: "style", name: "bento", description: "Cards", source: "builtin", pinned: true },
  { kind: "template", name: "sample", description: "Default", source: "builtin", pinned: false },
]

function renderChip(text: string, onChange = vi.fn(), onOpen = vi.fn()) {
  renderWithIntl(<ChoiceChip kind="style" text={text} onChange={onChange} items={items} loading={false} onOpen={onOpen} />)
  return { onChange, onOpen }
}

describe("setKindToken / tokenName", () => {
  it("sets, replaces and removes one kind and leaves the rest", () => {
    expect(setKindToken("a deck", "style", "bento")).toBe("@style:bento a deck")
    expect(setKindToken("@style:bento @template:sample a deck", "style", "aws-dark")).toBe("@style:aws-dark @template:sample a deck")
    expect(setKindToken("@style:bento a deck", "style", null)).toBe("a deck")
    expect(setKindToken("a deck", "style", "My Style")).toBe('@style:"My Style" a deck')
    expect(tokenName('@template:x @style:"My Style" a', "style")).toBe("My Style")
    expect(tokenName("a deck", "style")).toBeNull()
  })
})

describe("ChoiceChip", () => {
  it("is a dashed invitation while nothing is chosen", () => {
    renderChip("a deck")
    const chip = screen.getByRole("button", { name: "Choose a style" })
    expect(chip.parentElement!.className).toContain("border-dashed")
    expect(screen.queryByRole("button", { name: "Remove the style choice" })).toBeNull()
  })

  it("shows the chosen name from the input and removes it", () => {
    const { onChange } = renderChip("@style:bento a deck")
    expect(screen.getByRole("button", { name: "Style: bento" }).textContent).toContain("bento")
    fireEvent.click(screen.getByRole("button", { name: "Remove the style choice" }))
    expect(onChange).toHaveBeenCalledWith("a deck")
  })

  it("opens a gallery of this kind only, pinned first, and chooses from it", async () => {
    const { onChange, onOpen } = renderChip("a deck")
    fireEvent.click(screen.getByRole("button", { name: "Choose a style" }))
    expect(onOpen).toHaveBeenCalled()
    const options = await screen.findAllByRole("option")
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining("Agent picks"),
      expect.stringContaining("bento"),
      expect.stringContaining("aws-dark"),
    ])
    fireEvent.click(options[2])
    expect(onChange).toHaveBeenCalledWith("@style:aws-dark a deck")
  })

  it("filters by the search text", async () => {
    renderChip("a deck")
    fireEvent.click(screen.getByRole("button", { name: "Choose a style" }))
    fireEvent.change(await screen.findByRole("textbox", { name: "Search styles…" }), { target: { value: "console" } })
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      expect.stringContaining("Agent picks"),
      expect.stringContaining("aws-dark"),
    ])
  })
})
