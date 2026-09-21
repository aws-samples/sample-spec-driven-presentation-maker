// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, waitFor } from "@testing-library/react"
import { AnimatedSlidePreview } from "./AnimatedSlidePreview"

const defs = { version: 1, defs: "<defs />" }
const component = {
  class: "Graphic",
  bbox: { x: 200, y: 200, w: 300, h: 300 },
  text: "",
  svg: '<rect x="200" y="200" width="300" height="300" />',
  changed: true,
}

function mockFetch(compose: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
    const data = String(input).includes("defs") ? defs : compose
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: true,
    media: "(prefers-reduced-motion: reduce)",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("AnimatedSlidePreview layout regions", () => {
  it("renders labels and fills only the region overlapping a landed component", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [component],
      regions: [
        { name: "hero", x: 100, y: 100, w: 600, h: 600 },
        { name: "footer", x: 100, y: 800, w: 1600, h: 180 },
      ],
    })

    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" />
    )

    await waitFor(() => expect(container.querySelectorAll(".asp-region")).toHaveLength(2))
    expect(container.querySelectorAll(".asp-region-label")).toHaveLength(2)
    expect(container.textContent).toContain("hero")
    expect(container.textContent).toContain("footer")

    const hero = container.querySelector('[data-region-name="hero"].asp-region')
    const footer = container.querySelector('[data-region-name="footer"].asp-region')
    expect(hero?.classList.contains("asp-region-filled")).toBe(true)
    expect(footer?.classList.contains("asp-region-filled")).toBe(false)
    expect(hero?.querySelector("rect")?.getAttribute("vector-effect")).toBe("non-scaling-stroke")
  })

  it("clamps labels to the region width and hides them for tiny regions", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [{ ...component, changed: false }],
      regions: [
        { name: "a-very-long-region-name-that-would-spill-over", x: 96, y: 200, w: 480, h: 300 },
        { name: "tiny", x: 1500, y: 900, w: 60, h: 20 },
      ],
    })

    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" />
    )

    await waitFor(() => expect(container.querySelectorAll(".asp-region-label")).toHaveLength(2))
    const long = container.querySelector('.asp-region-label[data-region-name^="a-very"]') as HTMLElement
    expect(long.style.maxWidth).toBe("calc(25% - 12px)")
    const tiny = container.querySelector('.asp-region-label[data-region-name="tiny"]') as HTMLElement
    expect(tiny.classList.contains("asp-region-label-hidden")).toBe(true)
  })

  it("renders no region layer when compose data omits regions", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [{ ...component, changed: false }],
    })

    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" skipAnimation />
    )

    await waitFor(() => expect(container.querySelector("g[data-index=\"0\"]")).toBeTruthy())
    expect(container.querySelector(".asp-region")).toBeNull()
    expect(container.querySelector(".asp-region-label")).toBeNull()
  })

  async function renderRegions(components: Record<string, unknown>[], region = { name: "body", x: 100, y: 100, w: 800, h: 600 }) {
    mockFetch({ version: 1, viewBox: "0 0 1920 1080", bgFill: "#000", bgSvg: null, components, regions: [region] })
    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" />
    )
    await waitFor(() => expect(container.querySelectorAll(".asp-region")).toHaveLength(1))
    return container.querySelector(".asp-region") as SVGGElement
  }

  it("does not fill a region that a text frame merely touches at the edge", async () => {
    // Title frame: 40px into the region's top edge — far below the 50% criterion either way.
    const title = { ...component, text: "Title", bbox: { x: 100, y: 20, w: 800, h: 120 } }
    const region = await renderRegions([title])
    expect(region.classList.contains("asp-region-filled")).toBe(false)
  })

  it("fills a region from content that was already there (unchanged component)", async () => {
    const body = { ...component, text: "Body copy", changed: false, bbox: { x: 150, y: 150, w: 500, h: 300 } }
    const region = await renderRegions([body])
    expect(region.classList.contains("asp-region-filled")).toBe(true)
  })

  it("ignores decoration: a bare shape with no text or image inside the region", async () => {
    const bar = { ...component, class: "com.sun.star.drawing.CustomShape", text: "", svg: '<rect x="150" y="150" width="500" height="8" />', bbox: { x: 150, y: 150, w: 500, h: 8 } }
    const region = await renderRegions([bar])
    expect(region.classList.contains("asp-region-filled")).toBe(false)
  })

  it("fills a region covered by an image larger than the region", async () => {
    const picture = { ...component, class: "com.sun.star.drawing.CustomShape", text: "", svg: '<image href="x.webp" x="0" y="0" width="1200" height="900" />', bbox: { x: 0, y: 0, w: 1200, h: 900 } }
    const region = await renderRegions([picture])
    expect(region.classList.contains("asp-region-filled")).toBe(true)
  })

  it("keeps the region layer pointer-transparent so slide content stays selectable", async () => {
    const region = await renderRegions([{ ...component, text: "Body", changed: false }])
    expect(region.getAttribute("class")).toContain("asp-region")
    // Structural guard: the region <g> and its rect carry the classes that
    // globals.css maps to pointer-events: none.
    expect(region.querySelector("rect")?.getAttribute("class")).toBe("asp-region-rect")
  })
})

describe("AnimatedSlidePreview performance gating", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: false,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))
  })

  it("renders off-screen updates without agent cursors", async () => {
    class OffscreenObserver implements IntersectionObserver {
      readonly root = null
      readonly rootMargin = "0px"
  readonly scrollMargin = "0px"
      readonly thresholds = [0, 0.5]
      constructor(private callback: IntersectionObserverCallback) {}
      observe(target: Element) {
        this.callback([{
          target,
          isIntersecting: false,
          intersectionRatio: 0,
        } as IntersectionObserverEntry], this)
      }
      unobserve(): void {}
      disconnect(): void {}
      takeRecords(): IntersectionObserverEntry[] { return [] }
    }
    vi.stubGlobal("IntersectionObserver", OffscreenObserver)
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [component],
    })

    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" />
    )

    await waitFor(() => expect(container.querySelector('g[data-index="0"]')).toBeTruthy())
    expect(container.querySelector(".asp-overlay")).toBeNull()
    expect(container.textContent).not.toContain("Visual")
  })

  it("does not install a setInterval poll on mount", async () => {
    const intervalSpy = vi.spyOn(window, "setInterval")
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [{ ...component, changed: false }],
    })

    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" />
    )
    await waitFor(() => expect(container.querySelector('g[data-index="0"]')).toBeTruthy())
    expect(intervalSpy.mock.calls.some(([, delay]) => delay === 1000)).toBe(false)
  })

  it("skips per-slide defs fetching when the deck mounted them", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [{ ...component, changed: false }],
    })

    const { container } = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" defsMounted />
    )
    await waitFor(() => expect(container.querySelector('g[data-index="0"]')).toBeTruthy())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith("/compose.json")
  })
})
