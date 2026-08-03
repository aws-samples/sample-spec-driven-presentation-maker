// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SpecMarkdownPreview tests — artDirection result state:
 * HTML content → iframe (StyleSlidePreview), markdown content → prose.
 */

import { describe, it, expect, afterEach, beforeAll, afterAll, vi } from "vitest"
import { cleanup } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { SpecMarkdownPreview } from "./SpecMarkdownPreview"

afterEach(cleanup)

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

// Mock fetch for style-related API calls
vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })))

describe("SpecMarkdownPreview artDirection result state", () => {
  it("renders markdown content as prose (no iframe) when content is not HTML", () => {
    const mdContent = "# Art Direction\n\nThis is a **markdown** description of the style."

    const { container } = renderWithIntl(
      <SpecMarkdownPreview
        content={mdContent}
        specName="art-direction"
        specKey="artDirection"
        idToken="test-token"
      />
    )

    // Should have a prose article, not an iframe
    const article = container.querySelector("article.document-surface")
    expect(article).toBeTruthy()
    const iframes = container.querySelectorAll("iframe")
    expect(iframes.length).toBe(0)
  })

  it("renders HTML content via StyleSlidePreview (iframe present) when content starts with <", () => {
    const htmlContent = `<html><head><style>body{margin:0}</style></head><body><div class="slide cover">Hello</div></body></html>`

    // Mock getBoundingClientRect to provide non-zero width
    const originalGBCR = Element.prototype.getBoundingClientRect
    Element.prototype.getBoundingClientRect = function () {
      return { width: 600, height: 400, top: 0, left: 0, bottom: 400, right: 600, x: 0, y: 0, toJSON: () => ({}) }
    }

    const { container } = renderWithIntl(
      <SpecMarkdownPreview
        content={htmlContent}
        specName="art-direction"
        specKey="artDirection"
        idToken="test-token"
      />
    )

    // Should have iframe (from StyleSlidePreview), no prose article
    const iframes = container.querySelectorAll("iframe")
    expect(iframes.length).toBeGreaterThan(0)
    const article = container.querySelector("article.document-surface")
    expect(article).toBeNull()

    Element.prototype.getBoundingClientRect = originalGBCR
  })
})
