// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { SlidePreview } from "@/services/deckService"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: false }))

const viewMode = { current: "grid" as "grid" | "full" }
vi.mock("@/hooks/usePreferences", async () => {
  const { useState } = await import("react")
  return {
    usePreferences: () => {
      const [mode, setMode] = useState(viewMode.current)
      return { viewMode: mode, setViewMode: setMode, sendWithEnter: true, setSendWithEnter: () => {} }
    },
  }
})

import { SlideCarousel } from "./SlideCarousel"

const HTML_URL = "https://bucket.s3.amazonaws.com/html/d1/abc.html?X-Amz-Signature=x"
const slides = ["cover", "agenda", "body"].map((slug) => ({
  slug,
  previewUrl: `https://bucket.s3.amazonaws.com/html/d1/preview/${slug}_1.html?X-Amz-Signature=x`,
  composeUrl: null,
  updatedAt: "2026-10-30T00:00:00Z",
})) as unknown as SlidePreview[]

function renderCarousel(props: Partial<React.ComponentProps<typeof SlideCarousel>> = {}) {
  return renderWithIntl(
    <SlideCarousel
      slides={slides}
      deckId="d1"
      deckName="Deck"
      outputFormat="html"
      htmlUrl={HTML_URL}
      slideSize={{ width: 1920, height: 1080 }}
      workflowPhase="slides"
      {...props}
    />,
  )
}

describe("SlideCarousel — HTML decks", () => {
  beforeEach(() => { viewMode.current = "grid" })
  afterEach(cleanup)

  it("a grid click on slide N opens the player at reveal.js index N-1", () => {
    renderCarousel()
    const cards = screen.getAllByRole("button").filter((el) => el.querySelector("iframe"))
    expect(cards).toHaveLength(3)
    fireEvent.click(cards[2])
    expect(screen.getByTitle(/HTML deck/).getAttribute("src")).toBe(`${HTML_URL}#/2`)
  })

  it("a search jump (scrollToSlide) in the full view opens the player at that slide", async () => {
    viewMode.current = "full"
    const onScrollComplete = vi.fn()
    renderCarousel({ scrollToSlide: "agenda", onScrollComplete })
    await vi.waitFor(() => expect(onScrollComplete).toHaveBeenCalled())
    expect(screen.getByTitle(/HTML deck/).getAttribute("src")).toBe(`${HTML_URL}#/1`)
  })
})
