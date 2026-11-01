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
import { ReviewProvider } from "@/components/review/ReviewProvider"

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

  it("warns next to Present when slide scripts reach outside the deck", () => {
    renderCarousel({ scriptWarnings: [
      { slug: "agenda", kinds: ["navigation"] },
      { slug: "body", kinds: ["popup", "external-url"] },
    ] })
    const badge = screen.getByText("External access").closest("[title]")!
    const title = badge.getAttribute("title")!
    expect(title).toContain("agenda and body")
    expect(title).toContain("page navigation, new tabs, and external URLs")
    expect(badge.getAttribute("aria-label")).toBe(title)
    const present = screen.getByRole("button", { name: "Present in a new tab" })
    expect(badge.compareDocumentPosition(present) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("renders no comment tool without a ReviewProvider", () => {
    renderCarousel()
    expect(screen.queryByTitle("Comment on the slides (C)")).toBeNull()
    expect(document.querySelector("[data-review-layer]")).toBeNull()
  })

  it("shows no warning without script warnings", () => {
    renderCarousel({ scriptWarnings: [] })
    expect(screen.queryByText("External access")).toBeNull()
    cleanup()
    renderCarousel()
    expect(screen.queryByText("External access")).toBeNull()
  })
})

describe("SlideCarousel — comment tool", () => {
  beforeEach(() => {
    viewMode.current = "grid"
    localStorage.clear()
  })
  afterEach(cleanup)

  function renderWithReview(enabled = true, format: "html" | "pptx" = "html") {
    const deckSlides = format === "html" ? slides : slides.map((s) => ({ ...s, previewUrl: `https://bucket.s3.amazonaws.com/d1/${s.slug}.png` }))
    return renderWithIntl(
      <ReviewProvider deckId="d1" slugs={slides.map((s) => s.slug)} enabled={enabled} agentBusy={false} openChat={() => {}}>
        <SlideCarousel
          slides={deckSlides}
          deckId="d1"
          deckName="Deck"
          outputFormat={format}
          htmlUrl={HTML_URL}
          slideSize={{ width: 1920, height: 1080 }}
          workflowPhase="slides"
        />
      </ReviewProvider>,
    )
  }
  const toolButton = () => screen.getByTitle("Comment on the slides (C)")
  const layers = () => document.querySelectorAll("[data-review-layer]")

  it("C toggles the tool", () => {
    renderWithReview()
    expect(toolButton().getAttribute("aria-pressed")).toBe("false")
    fireEvent.keyDown(window, { key: "c" })
    expect(toolButton().getAttribute("aria-pressed")).toBe("true")
    fireEvent.keyDown(window, { key: "c" })
    expect(toolButton().getAttribute("aria-pressed")).toBe("false")
  })

  it("turning the tool on in the grid switches to the full view (R1.5)", () => {
    renderWithReview()
    expect(layers()).toHaveLength(0)
    fireEvent.click(toolButton())
    expect(layers()).toHaveLength(3)
    expect(screen.getByRole("status").textContent).toContain("Drag to outline")
  })

  it("HTML decks show the stacked static previews instead of the player while the tool is on", () => {
    viewMode.current = "full"
    renderWithReview()
    expect(screen.getByTitle(/HTML deck/)).not.toBeNull()
    expect(layers()).toHaveLength(0)
    fireEvent.click(toolButton())
    expect(screen.queryByTitle(/HTML deck/)).toBeNull()
    expect(layers()).toHaveLength(3)
    expect(document.querySelectorAll("iframe")).toHaveLength(3)
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.getByTitle(/HTML deck/)).not.toBeNull()
  })

  it("the slide-hover button turns the tool on (PPTX full view)", () => {
    viewMode.current = "full"
    renderWithReview(true, "pptx")
    expect(layers()).toHaveLength(3)
    const cta = screen.getAllByTitle("Comment on this slide (C)")
    expect(cta).toHaveLength(3)
    fireEvent.click(cta[1])
    expect(toolButton().getAttribute("aria-pressed")).toBe("true")
    expect(screen.queryAllByTitle("Comment on this slide (C)")).toHaveLength(0)
  })

  it("the slide-hover button on the HTML player turns the tool on (R1.2)", () => {
    viewMode.current = "full"
    renderWithReview()
    expect(screen.getByTitle(/HTML deck/)).not.toBeNull()
    const cta = screen.getAllByTitle("Comment on this slide (C)")
    expect(cta).toHaveLength(1)
    // The deck iframe takes the pointer, so the pane around the player marks the hover.
    const box = screen.getByTitle(/HTML deck/).parentElement!
    const zone = document.querySelector("[data-slide-scroller]")!
    expect(box.hasAttribute("data-hover")).toBe(false)
    fireEvent.mouseEnter(zone)
    expect(box.hasAttribute("data-hover")).toBe(true)
    fireEvent.mouseLeave(zone)
    expect(box.hasAttribute("data-hover")).toBe(false)
    fireEvent.mouseEnter(zone)
    fireEvent.click(cta[0])
    expect(toolButton().getAttribute("aria-pressed")).toBe("true")
    expect(screen.queryByTitle(/HTML deck/)).toBeNull()
    expect(layers()).toHaveLength(3)
  })

  it("shows no tool when the provider is disabled", () => {
    renderWithReview(false)
    expect(screen.queryByTitle("Comment on the slides (C)")).toBeNull()
    fireEvent.keyDown(window, { key: "c" })
    expect(layers()).toHaveLength(0)
  })
})
