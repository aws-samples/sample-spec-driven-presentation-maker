// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Live Design Studio design-system regression tests.
 * Verifies agent tokens, theme behavior, primary actions, and semantic surfaces.
 */

import { describe, it, expect } from "vitest"
import { screen, fireEvent } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { HearingCard } from "@/components/chat/HearingCard"
import fs from "fs"
import path from "path"

const sourcePath = (...parts: string[]) => path.resolve(process.cwd(), "src", ...parts)

describe("Agent token mapping (globals.css)", () => {
  const css = fs.readFileSync(sourcePath("app/globals.css"), "utf-8")

  it("defines five agent tokens in :root", () => {
    expect(css).toContain("--agent-layout:")
    expect(css).toContain("--agent-content:")
    expect(css).toContain("--agent-visual:")
    expect(css).toContain("--agent-data:")
    expect(css).toContain("--agent-decorator:")
  })

  it("defines team-gradient using agent tokens", () => {
    expect(css).toContain("--team-gradient:")
    expect(css).toContain("var(--agent-layout)")
    expect(css).toContain("var(--agent-decorator)")
  })

  it("defines team-action-btn with conic-gradient", () => {
    expect(css).toContain(".team-action-btn")
    expect(css).toContain("conic-gradient")
    expect(css).toContain("--team-angle")
  })

  it("keeps New Deck spectrum restrained and theme-aware", () => {
    expect(css).toContain("--entry-action-spectrum:")
    expect(css).toContain(".team-entry-btn {")
    expect(css).toContain("box-shadow: none")
    expect(css).toContain("animation-duration: 7s")
    expect(css).toContain("[data-theme=\"light\"] .team-entry-btn::before")
    expect(css).toContain("inset: -2px")

    const desktop = fs.readFileSync(sourcePath("components/deck/DeckListView.tsx"), "utf-8")
    const mobile = fs.readFileSync(sourcePath("app/(authenticated)/decks/page.tsx"), "utf-8")
    expect(desktop).toContain("team-action-btn team-entry-btn")
    expect(mobile).toContain("team-action-btn team-entry-btn")
  })

  it("styles MUST NOT without striking through its text", () => {
    expect(css).toContain(".requirement-must-not::before")
    expect(css).toContain(".requirement-must-not::after")
  })

  it("disables team-action animation in reduced-motion", () => {
    expect(css).toContain(".team-action-btn::before { animation: none; }")
  })

  it("no longer contains hardcoded oklch(0.75 0.14 185 teal", () => {
    expect(css).not.toContain("oklch(0.75 0.14 185)")
  })

  it("keeps prose colors theme-aware", () => {
    expect(css).toContain("--tw-prose-body: var(--foreground-secondary)")
    expect(css).toContain("--tw-prose-headings: var(--foreground)")
    expect(css).not.toContain("--tw-prose-body: oklch(0.85 0 0)")
  })

  it("keeps text-xs at the 11px floor at 90% scale", () => {
    expect(css).toContain(".text-xs { font-size: max(11px, 0.75rem); }")
  })

  it("disables content and composer entrance motion", () => {
    expect(css).toContain(".content-enter,")
    expect(css).toContain(".compose-agent-enter { animation: none !important")
  })
})

describe("HearingCard — achromatic + five-color spine", () => {
  const baseProps = {
    inference: "Test inference",
    questions: [
      {
        id: "q1",
        type: "single_select" as const,
        text: "Pick one",
        options: ["A", "B"],
        recommended: "A",
      },
    ],
    onSubmit: () => {},
  }

  it("renders a 3px vertical five-color spine", () => {
    const { container } = renderWithIntl(<HearingCard {...baseProps} />)
    const spine = container.querySelector("[style*='--team-spine-gradient']") as HTMLElement
    expect(spine).toBeTruthy()
    expect(spine.style.width).toBe("3px")
  })

  it("renders submit button with team-action-btn class", () => {
    renderWithIntl(<HearingCard {...baseProps} />)
    const btns = screen.getAllByRole("button")
    const submitBtn = btns.find(b => b.className.includes("team-action-btn"))
    expect(submitBtn).toBeTruthy()
  })

  it("uses achromatic selected chip (bg-foreground class)", () => {
    const { container } = renderWithIntl(<HearingCard {...baseProps} />)
    const chips = screen.getAllByRole("radio")
    const chipA = chips.find(c => c.textContent === "A")!
    // Click to select
    fireEvent.click(chipA)
    expect(chipA.className).toContain("bg-foreground")
  })

  it("recommendation dot uses agent-data class", () => {
    const { container } = renderWithIntl(<HearingCard {...baseProps} />)
    // "A" is recommended but not selected initially → dot visible
    const dot = container.querySelector(".bg-agent-data")
    expect(dot).toBeTruthy()
  })
})

describe("AnimatedSlidePreview — no hardcoded AGENTS colors", () => {
  it("source file does not contain rgba agent colors", () => {
    const src = fs.readFileSync(
      sourcePath("components/deck/AnimatedSlidePreview.tsx"),
      "utf-8"
    )
    // Old hardcoded values should be gone
    expect(src).not.toContain("rgba(100,150,255")
    expect(src).not.toContain("rgba(80,210,180")
    expect(src).not.toContain("rgba(170,120,255")
    expect(src).not.toContain("#3b6cf0")
    expect(src).not.toContain("#2ba882")
    // Should use CSS variable approach
    expect(src).toContain("--agent-layout")
    expect(src).toContain("resolveAgents")
  })
})

describe("Document typography cleanup", () => {
  it("lets document-surface own Outline font family", () => {
    const src = fs.readFileSync(sourcePath("components/deck/OutlineView.tsx"), "utf-8")
    expect(src).not.toContain("font-[var(--font-document)]")
    expect(src).toContain("document-surface")
  })
})

describe("Light/Dark theme audit — no hardcoded white chrome", () => {
  const chromeFiles = [
    "components/Settings.tsx",
    "components/ConfirmDialog.tsx",
    "components/AppShell.tsx",
    "components/ModelPicker.tsx",
    "components/chat/ChatInput.tsx",
    "components/chat/ModeSelector.tsx",
    "components/chat/ChatPanelShell.tsx",
    "components/chat/StyleChatShell.tsx",
    "components/deck/TemplatePickerSection.tsx",
    "components/deck/SpecMarkdownPreview.tsx",
    "components/deck/StyleCard.tsx",
  ]

  chromeFiles.forEach((file) => {
    it(`${file} has no border-white/[...] in chrome`, () => {
      const src = fs.readFileSync(sourcePath(file), "utf-8")
      // Should not have hardcoded white borders (use border-border or border-border-hover)
      const matches = src.match(/border-white\/\[/g) || []
      expect(matches).toHaveLength(0)
    })
  })

  it("ConfirmDialog uses bg-popover instead of hardcoded oklch bg", () => {
    const src = fs.readFileSync(
      sourcePath("components/ConfirmDialog.tsx"),
      "utf-8"
    )
    expect(src).toContain("bg-popover")
    expect(src).not.toContain("bg-[oklch(")
  })

  it("styles/page popover menu uses bg-popover", () => {
    const src = fs.readFileSync(
      sourcePath("app/(authenticated)/styles/page.tsx"),
      "utf-8"
    )
    expect(src).not.toContain("oklch(0.14 0.005 260 / 98%)")
    expect(src).toContain("bg-popover")
  })

  it("templates/page upload dialog uses bg-popover", () => {
    const src = fs.readFileSync(
      sourcePath("app/(authenticated)/templates/page.tsx"),
      "utf-8"
    )
    expect(src).not.toContain("oklch(0.14 0.005 260)")
    expect(src).toContain("bg-popover")
  })
})
