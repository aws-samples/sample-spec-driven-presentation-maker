// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render, waitFor } from "@testing-library/react"
import { AnimatedSlidePreview } from "./AnimatedSlidePreview"
import { resetAnimationSchedulerForTests } from "./animationScheduler"

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
  resetAnimationSchedulerForTests()
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
  resetAnimationSchedulerForTests()
  vi.restoreAllMocks()
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


  it("falls back to per-slide defs when deck-level defs are unavailable", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [{ ...component, changed: false }],
    })

    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose-1.json" defsMounted />
    )
    await waitFor(() => expect(rendered.container.querySelector('g[data-index="0"]')).toBeTruthy())
    expect(fetch).not.toHaveBeenCalledWith("/defs.json")

    rendered.rerender(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose-2.json" defsMounted={false} />
    )
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/defs.json"))
  })

  it("accumulates unsettled changed indices across off-screen updates", async () => {
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
    const first = { ...component, changed: true }
    const second = { ...component, bbox: { x: 600, y: 200, w: 300, h: 300 }, changed: false }
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const url = String(input)
      const data = url.includes("defs") ? defs : {
        version: 1,
        viewBox: "0 0 1920 1080",
        bgFill: "#000",
        bgSvg: null,
        components: url.includes("compose-2")
          ? [{ ...second, changed: true }, { ...first, changed: false }]
          : [first, second],
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
    }))

    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose-1.json" />
    )
    await waitFor(() => expect(rendered.container.querySelector('g[data-index="0"]')?.getAttribute("data-unsettled")).toBe("true"))

    rendered.rerender(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose-2.json" />
    )
    await waitFor(() => expect(rendered.container.querySelector('g[data-index="0"]')?.getAttribute("data-unsettled")).toBe("true"))
    // The first component moved from index 0 to 1 but remains accumulated by identity.
    expect(rendered.container.querySelector('g[data-index="1"]')?.getAttribute("data-unsettled")).toBe("true")
    expect(rendered.container.querySelector(".asp-overlay")).toBeNull()
  })
})


class ControlledObserver implements IntersectionObserver {
  static instances: ControlledObserver[] = []
  readonly root = null
  readonly rootMargin = "0px"
  readonly scrollMargin = "0px"
  readonly thresholds = [0, 0.5]
  readonly targets = new Set<Element>()

  constructor(private callback: IntersectionObserverCallback) {
    ControlledObserver.instances.push(this)
  }

  observe(target: Element) { this.targets.add(target) }
  unobserve(target: Element) { this.targets.delete(target) }
  disconnect() { this.targets.clear() }
  takeRecords(): IntersectionObserverEntry[] { return [] }

  emit(target: Element, visible: boolean) {
    this.callback([{
      target,
      isIntersecting: visible,
      intersectionRatio: visible ? 1 : 0,
    } as IntersectionObserverEntry], this)
  }

  static emit(target: Element, visible: boolean) {
    const observer = ControlledObserver.instances.find((candidate) => candidate.targets.has(target))
    if (!observer) throw new Error("No observer owns target")
    observer.emit(target, visible)
  }
}

describe("AnimatedSlidePreview visibility and error races", () => {
  beforeEach(() => {
    ControlledObserver.instances = []
    vi.stubGlobal("IntersectionObserver", ControlledObserver)
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

  it("waits for the first IO result, then animates a slide visible on mount without unsettling it", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [component],
    })
    const onAnimate = vi.fn()
    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" slug="visible" onAnimate={onAnimate} />
    )
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    expect(rendered.container.querySelector('g[data-index="0"]')).toBeNull()

    const wrapper = rendered.container.querySelector('[data-slide-id="visible"]')!
    act(() => ControlledObserver.emit(wrapper, true))

    await waitFor(() => expect(onAnimate).toHaveBeenCalledTimes(1))
    expect(rendered.container.querySelector('g[data-index="0"]')?.hasAttribute("data-unsettled")).toBe(false)
  })

  it("drops a queued animation when the slide becomes hidden and applies the unsettled final SVG", async () => {
    mockFetch({
      version: 1,
      viewBox: "0 0 1920 1080",
      bgFill: "#000",
      bgSvg: null,
      components: [component],
    })
    const callbacks = [vi.fn(), vi.fn(), vi.fn()]
    const first = render(<AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/one.json" slug="one" onAnimate={callbacks[0]} />)
    const second = render(<AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/two.json" slug="two" onAnimate={callbacks[1]} />)
    const third = render(<AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/three.json" slug="three" onAnimate={callbacks[2]} />)
    const wrappers = [first, second, third].map((view, index) => view.container.querySelector(`[data-slide-id="${["one", "two", "three"][index]}"]`)!)

    act(() => wrappers.forEach((wrapper) => ControlledObserver.emit(wrapper, true)))
    await waitFor(() => {
      expect(callbacks[0]).toHaveBeenCalledTimes(1)
      expect(callbacks[1]).toHaveBeenCalledTimes(1)
    })
    expect(callbacks[2]).not.toHaveBeenCalled()

    act(() => ControlledObserver.emit(wrappers[2], false))
    first.unmount()

    await waitFor(() => expect(third.container.querySelector('g[data-index="0"]')).toBeTruthy())
    const landed = third.container.querySelector('g[data-index="0"]') as SVGGElement
    expect(callbacks[2]).not.toHaveBeenCalled()
    expect(third.container.querySelector(".asp-overlay")).toBeNull()
    expect(landed.style.opacity).not.toBe("0")
    expect(landed.dataset.unsettled).toBe("true")
  })

  it("merges changed keys from a superseded hidden response into the current unsettled set", async () => {
    const first = { ...component, svg: '<rect id="first" x="200" y="200" width="300" height="300" />' }
    const second = { ...component, bbox: { x: 600, y: 200, w: 300, h: 300 }, svg: '<rect id="second" x="600" y="200" width="300" height="300" />' }
    const pending = new Map<string, (response: { ok: boolean; status: number; json: () => Promise<unknown> }) => void>()
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => new Promise((resolve) => {
      pending.set(String(input), resolve)
    })))
    const respond = (url: string, components: Record<string, unknown>[]) => {
      pending.get(url)?.({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ version: 1, viewBox: "0 0 1920 1080", bgFill: "#000", bgSvg: null, components }),
      })
    }

    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose-1.json" slug="rapid" defsMounted />
    )
    const wrapper = rendered.container.querySelector('[data-slide-id="rapid"]')!
    act(() => ControlledObserver.emit(wrapper, false))
    await waitFor(() => expect(pending.has("/compose-1.json")).toBe(true))

    rendered.rerender(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose-2.json" slug="rapid" defsMounted />
    )
    await waitFor(() => expect(pending.has("/compose-2.json")).toBe(true))
    act(() => respond("/compose-2.json", [{ ...first, changed: false }, { ...second, changed: true }]))
    await waitFor(() => expect(rendered.container.querySelector('g[data-component-key="id:second"]')?.getAttribute("data-unsettled")).toBe("true"))

    act(() => respond("/compose-1.json", [{ ...first, changed: true }, { ...second, changed: false }]))
    await waitFor(() => expect(rendered.container.querySelector('g[data-component-key="id:first"]')?.getAttribute("data-unsettled")).toBe("true"))
    expect(rendered.container.querySelector('g[data-component-key="id:second"]')?.getAttribute("data-unsettled")).toBe("true")
  })

  it("shows the fallback immediately when an initial compose request returns 404", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
      ok: false,
      status: 404,
      json: () => Promise.resolve({}),
    })))
    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/missing-initial.json" defsMounted fallback={<div>fallback</div>} />
    )

    await waitFor(() => expect(rendered.container.querySelector("[data-fallback]")).toBeTruthy())
    expect(rendered.container.querySelector("svg")).toBeNull()
  })

  it("keeps the previous SVG and schedules retry for a transient 404 without showing fallback", async () => {
    const timeoutSpy = vi.spyOn(window, "setTimeout")
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.includes("defs")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(defs) })
      if (url.includes("missing")) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ version: 1, viewBox: "0 0 1920 1080", bgFill: "#000", bgSvg: null, components: [{ ...component, changed: false }] }),
      })
    }))
    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/good.json" skipAnimation fallback={<div>fallback</div>} />
    )
    const wrapper = rendered.container.querySelector(".slide-cv")!
    act(() => ControlledObserver.emit(wrapper, true))
    await waitFor(() => expect(rendered.container.querySelector('g[data-index="0"]')).toBeTruthy())

    rendered.rerender(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/missing.json" skipAnimation fallback={<div>fallback</div>} />
    )
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/missing.json"))
    await waitFor(() => expect(timeoutSpy.mock.calls.some(([, delay]) => delay === 2000)).toBe(true))
    expect(rendered.container.querySelector('g[data-index="0"]')).toBeTruthy()
    expect(rendered.container.querySelector("[data-fallback]")).toBeNull()
  })

  it("shows a permanent payload error without scheduling retries until composeUrl changes", async () => {
    const timeoutSpy = vi.spyOn(window, "setTimeout")
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const data = String(input).includes("defs")
        ? defs
        : { version: 2, viewBox: "0 0 1920 1080", bgFill: "#000", bgSvg: null, components: [component] }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) })
    }))
    const rendered = render(
      <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/bad-schema.json" fallback={<div>fallback</div>} />
    )

    await waitFor(() => expect(rendered.container.querySelector("[data-fallback]")).toBeTruthy())
    expect(timeoutSpy.mock.calls.some(([, delay]) => delay === 2000)).toBe(false)
  })
})
