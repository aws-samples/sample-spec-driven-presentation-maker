// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { PickerItem } from "@/lib/slashToken"
import { SlashTokenReflection } from "./SlashTokenReflection"

const items: PickerItem[] = [
  {
    kind: "template",
    name: "My Brand (2026)",
    description: "Branded template",
    source: "user",
    pinned: false,
    themeColors: { background: "#ffffff", accent1: "#ff9900", accent2: "#146eb4" },
  },
  {
    kind: "style",
    name: "lumina",
    description: "Bright style",
    source: "builtin",
    pinned: true,
  },
]

afterEach(cleanup)

describe("SlashTokenReflection", () => {
  it("renders nothing when text contains no slash tokens", () => {
    const { container } = renderWithIntl(
      <SlashTokenReflection text="Create a launch deck" items={items} onRemove={() => {}} />,
    )

    expect(container.firstChild).toBeNull()
  })

  it("derives known quoted and bare token chips from text", () => {
    renderWithIntl(
      <SlashTokenReflection
        text={'Use @template:"My Brand (2026)" with @style:lumina'}
        items={items}
        onRemove={() => {}}
      />,
    )

    expect(screen.getByText("My Brand (2026)")).toBeTruthy()
    expect(screen.getByText("lumina")).toBeTruthy()
    expect(screen.getByText("Template")).toBeTruthy()
    expect(screen.getByText("Style")).toBeTruthy()
    expect(screen.queryByTitle("This template or style is unavailable")).toBeNull()
  })

  it("warns when a token name is unavailable", () => {
    renderWithIntl(
      <SlashTokenReflection text="Use @style:missing" items={items} onRemove={() => {}} />,
    )

    const chip = screen.getByTitle("This template or style is unavailable")
    expect(chip.className).toContain("border-dashed")
    expect(screen.getByText("missing")).toBeTruthy()
  })

  it("does not flag tokens as unavailable before the catalogue has loaded", () => {
    renderWithIntl(
      <SlashTokenReflection text="Use @style:lumina" items={[]} onRemove={() => {}} />,
    )

    expect(screen.queryByTitle("This template or style is unavailable")).toBeNull()
  })

  it("reports the parsed token match when remove is clicked", () => {
    const onRemove = vi.fn()
    renderWithIntl(
      <SlashTokenReflection text="Use @style:lumina now" items={items} onRemove={onRemove} />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Remove Style lumina" }))
    expect(onRemove).toHaveBeenCalledWith({
      kind: "style",
      name: "lumina",
      start: 4,
      end: 17,
    })
  })
})
