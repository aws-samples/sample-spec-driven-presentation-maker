// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleSlidePreview tests — splitStyleSlides pure function + component rendering.
 */

import { describe, it, expect, afterEach, beforeAll, afterAll } from "vitest"
import { screen, cleanup } from "@testing-library/react"
import { render } from "@testing-library/react"
import { splitStyleSlides, StyleSlidePreview, buildCoverDoc } from "./StyleSlidePreview"

afterEach(cleanup)

describe("splitStyleSlides", () => {
  it("splits 3-slide HTML into 3 entries", () => {
    const html = `<!DOCTYPE html><html><head><style>.slide{width:1920px}</style></head><body>
<div class="slide cover">Slide 1 content</div>
<div class="slide body">Slide 2 content</div>
<div class="slide closing">Slide 3 content</div>
</body></html>`

    const result = splitStyleSlides(html)
    expect(result).not.toBeNull()
    expect(result!.slides).toHaveLength(3)
    expect(result!.head).toContain(".slide{width:1920px}")
    expect(result!.slides[0]).toContain("Slide 1 content")
    expect(result!.slides[1]).toContain("Slide 2 content")
    expect(result!.slides[2]).toContain("Slide 3 content")
  })

  it("returns null when no .slide divs are found", () => {
    const html = `<html><head><style>body{}</style></head><body><p>No slides here</p></body></html>`
    expect(splitStyleSlides(html)).toBeNull()
  })

  it("handles nested divs inside a slide without breaking", () => {
    const html = `<html><head><title>Test</title></head><body>
<div class="slide cover"><div class="inner"><div class="deep">Nested</div></div></div>
<div class="slide body"><div class="wrapper">Content</div></div>
</body></html>`

    const result = splitStyleSlides(html)
    expect(result).not.toBeNull()
    expect(result!.slides).toHaveLength(2)
    expect(result!.slides[0]).toContain("Nested")
    expect(result!.slides[0]).toContain("class=\"inner\"")
    expect(result!.slides[1]).toContain("Content")
  })

  it("handles slides with class attribute variations", () => {
    const html = `<html><head></head><body>
<div class="slide">Simple</div>
<div class="slide custom-class">With extra class</div>
</body></html>`

    const result = splitStyleSlides(html)
    expect(result).not.toBeNull()
    expect(result!.slides).toHaveLength(2)
  })

  it("extracts head content correctly", () => {
    const html = `<html><head><meta charset="utf-8"><style>h1{color:red}</style><link rel="stylesheet" href="x.css"></head><body>
<div class="slide cover">Title</div>
</body></html>`

    const result = splitStyleSlides(html)
    expect(result).not.toBeNull()
    expect(result!.head).toContain("charset")
    expect(result!.head).toContain("h1{color:red}")
    expect(result!.head).toContain("link")
  })
})

const SPRITE = `<svg width="0" height="0" style="position:absolute" aria-hidden="true" data-sdpm-icons><symbol id="material/hub" viewBox="0 0 1 1"><path d="M0 0"/></symbol></svg>`
const ICON_STYLE = `<html><head><style>.slide{width:1920px}</style></head><body class="x">
${SPRITE}
<div class="slide cover"><svg class="icon"><use href="#material/hub"/></svg>S1</div>
<div class="slide body">S2<svg><symbol id="local/x"><path/></symbol></svg></div>
</body></html>`

describe("icon sprite prelude", () => {
  it("collects the sprite between <body> and the first slide", () => {
    const result = splitStyleSlides(ICON_STYLE)!
    expect(result.prelude).toBe(SPRITE)
    // a symbol inside a slide stays with its slide
    expect(result.prelude).not.toContain("local/x")
  })

  it("carries the sprite into the cover document", () => {
    const cover = buildCoverDoc(ICON_STYLE)
    expect(cover).toContain(`<body>${SPRITE}<div class="slide cover">`)
    expect(cover).not.toContain("S2")
  })

  it("is empty without a sprite, leaving the cover as before", () => {
    const html = `<html><head></head><body>\n<svg class="deco"><circle/></svg>\n<div class="slide cover">S1</div></body></html>`
    expect(splitStyleSlides(html)!.prelude).toBe("")
    expect(buildCoverDoc(html)).toContain(`<body><div class="slide cover">S1</body>`)
  })
})

describe("buildCoverDoc", () => {
  it("returns first slide only with zoom reset injected when .slide markers exist", () => {
    const html = `<!DOCTYPE html><html><head><style>.slide{width:1920px}</style></head><body>
<div class="slide cover">Slide 1</div>
<div class="slide body">Slide 2</div>
<div class="slide closing">Slide 3</div>
</body></html>`

    const result = buildCoverDoc(html)
    expect(result).toContain("Slide 1")
    expect(result).not.toContain("Slide 2")
    expect(result).not.toContain("Slide 3")
    // Zoom reset injected
    expect(result).toContain("zoom:1!important")
    expect(result).toContain("data-preview-reset")
  })

  it("returns full HTML as-is when no .slide markers found", () => {
    const html = `<html><head><style>body{color:red}</style></head><body><p>No slides here</p></body></html>`
    const result = buildCoverDoc(html)
    expect(result).toBe(html)
  })

  it("preserves head styles in the cover document", () => {
    const html = `<html><head><style>h1{font-size:72px}</style></head><body>
<div class="slide cover"><h1>Title</h1></div>
<div class="slide body">Content</div>
</body></html>`

    const result = buildCoverDoc(html)
    expect(result).toContain("h1{font-size:72px}")
    expect(result).toContain("<h1>Title</h1>")
  })
})

describe("StyleSlidePreview component", () => {
  // Mock ResizeObserver for JSDOM
  const originalRO = globalThis.ResizeObserver
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver
  })
  afterAll(() => { globalThis.ResizeObserver = originalRO })

  it("shows loading spinner when loading=true", () => {
    const { container } = render(<StyleSlidePreview html="<p>test</p>" loading={true} />)
    expect(container.querySelector(".animate-spin")).toBeTruthy()
  })

  it("shows loading spinner when html is empty", () => {
    const { container } = render(<StyleSlidePreview html="" loading={false} />)
    expect(container.querySelector(".animate-spin")).toBeTruthy()
  })

  it("renders multiple iframes with slide titles when slides are split", () => {
    // We need to simulate containerWidth > 0 via getBoundingClientRect
    const originalGBCR = Element.prototype.getBoundingClientRect
    Element.prototype.getBoundingClientRect = function () {
      return { width: 600, height: 400, top: 0, left: 0, bottom: 400, right: 600, x: 0, y: 0, toJSON: () => ({}) }
    }

    const html = `<html><head><style>body{margin:0}</style></head><body>
<div class="slide cover">S1</div>
<div class="slide body">S2</div>
<div class="slide closing">S3</div>
</body></html>`

    const { container } = render(<StyleSlidePreview html={html} loading={false} />)
    const iframes = container.querySelectorAll("iframe")
    expect(iframes.length).toBe(3)
    expect(iframes[0].title).toBe("Slide 1")
    expect(iframes[1].title).toBe("Slide 2")
    expect(iframes[2].title).toBe("Slide 3")

    // Number rail
    expect(screen.getByText("1")).toBeTruthy()
    expect(screen.getByText("2")).toBeTruthy()
    expect(screen.getByText("3")).toBeTruthy()

    Element.prototype.getBoundingClientRect = originalGBCR
  })

  it("gives every slide card the icon sprite", () => {
    const originalGBCR = Element.prototype.getBoundingClientRect
    Element.prototype.getBoundingClientRect = function () {
      return { width: 600, height: 400, top: 0, left: 0, bottom: 400, right: 600, x: 0, y: 0, toJSON: () => ({}) }
    }

    const { container } = render(<StyleSlidePreview html={ICON_STYLE} loading={false} />)
    const iframes = container.querySelectorAll("iframe")
    expect(iframes.length).toBe(2)
    for (const iframe of iframes) expect(iframe.getAttribute("srcdoc")).toContain(`<body>${SPRITE}<div class="slide`)

    Element.prototype.getBoundingClientRect = originalGBCR
  })

  it("renders single fallback iframe when no .slide markers", () => {
    const originalGBCR = Element.prototype.getBoundingClientRect
    Element.prototype.getBoundingClientRect = function () {
      return { width: 600, height: 400, top: 0, left: 0, bottom: 400, right: 600, x: 0, y: 0, toJSON: () => ({}) }
    }

    const html = `<html><head></head><body><p>Plain HTML, no slides</p></body></html>`
    const { container } = render(<StyleSlidePreview html={html} loading={false} />)
    const iframes = container.querySelectorAll("iframe")
    expect(iframes.length).toBe(1)
    expect(iframes[0].title).toBe("Style Preview")

    Element.prototype.getBoundingClientRect = originalGBCR
  })
})
