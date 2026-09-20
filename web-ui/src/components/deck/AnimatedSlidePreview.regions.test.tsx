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
})
