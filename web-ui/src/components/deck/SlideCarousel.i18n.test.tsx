// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { SlidePreview } from "@/services/deckService"

// The Folder button only renders in Local mode.
vi.mock("@/lib/mode", () => ({ IS_LOCAL: true }))
vi.mock("@/hooks/usePreferences", () => ({
  usePreferences: () => ({ viewMode: "grid", setViewMode: () => {}, sendWithEnter: true, setSendWithEnter: () => {} }),
}))

import { SlideCarousel } from "./SlideCarousel"

const slides = Array.from({ length: 7 }, (_, i) => ({
  slug: `s${i}`,
  previewUrl: `/api/decks/d1/preview/s${i}.png`,
  composeUrl: null,
  updatedAt: "2026-10-30T00:00:00Z",
})) as unknown as SlidePreview[]

function renderHeader(locale: "en" | "ja", count = 7) {
  return renderWithIntl(
    <SlideCarousel slides={slides.slice(0, count)} deckId="d1" deckName="Deck" pptxUrl="/out.pptx" ownerAlias="alice" workflowPhase="slides" />,
    { locale },
  )
}

describe("SlideCarousel — header i18n", () => {
  afterEach(cleanup)

  it("translates the slide count, owner and Folder button in Japanese", () => {
    renderHeader("ja")
    expect(screen.getByText("スライド 7 枚")).toBeTruthy()
    expect(screen.getByText("· 作成者: alice")).toBeTruthy()
    expect(screen.getByRole("button", { name: "フォルダを開く" }).textContent).toBe("フォルダ")
    expect(screen.queryByText(/slides?\b/)).toBeNull()
  })

  it("keeps the English plural forms", () => {
    renderHeader("en", 1)
    expect(screen.getByText("1 slide")).toBeTruthy()
    cleanup()
    renderHeader("en")
    expect(screen.getByText("7 slides")).toBeTruthy()
    expect(screen.getByText("· by alice")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Open folder" }).textContent).toBe("Folder")
  })
})
