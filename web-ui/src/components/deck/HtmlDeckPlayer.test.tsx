// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { HtmlDeckPlayer, deckUrlAtSlide } from "./HtmlDeckPlayer"

afterEach(cleanup)

const URL_1 = "https://bucket.s3.ap-northeast-1.amazonaws.com/html/d1/abc.html?X-Amz-Signature=1"

describe("HtmlDeckPlayer", () => {
  it("isolates the deck: exact sandbox and allow attributes, never allow-same-origin", () => {
    renderWithIntl(<HtmlDeckPlayer htmlUrl={URL_1} deckName="Launch" />)

    const frame = screen.getByTitle("HTML deck: Launch") as HTMLIFrameElement
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-popups allow-popups-to-escape-sandbox")
    expect(frame.getAttribute("allow")).toBe("fullscreen *")
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer")
    expect(frame.getAttribute("src")).toBe(URL_1)
    const tokens = frame.getAttribute("sandbox")!.split(/\s+/)
    expect(tokens).not.toContain("allow-same-origin")
    expect(tokens).not.toContain("allow-modals")
    expect(tokens.filter((t) => t.startsWith("allow-top-navigation"))).toEqual([])
  })

  it("follows the deck aspect ratio", () => {
    renderWithIntl(<HtmlDeckPlayer htmlUrl={URL_1} slideSize={{ width: 1280, height: 960 }} />)
    const wrapper = screen.getByTitle("HTML deck").parentElement as HTMLElement
    expect(wrapper.style.aspectRatio).toBe("1280/960")
  })

  it("keeps the loaded deck when only the signature changes, reloads on a new build", () => {
    const { rerender } = renderWithIntl(<HtmlDeckPlayer htmlUrl={URL_1} />)
    rerender(<HtmlDeckPlayer htmlUrl={URL_1.replace("Signature=1", "Signature=2")} />)
    expect(screen.getByTitle("HTML deck").getAttribute("src")).toBe(URL_1)

    const next = "https://bucket.s3.ap-northeast-1.amazonaws.com/html/d1/def.html?X-Amz-Signature=3"
    rerender(<HtmlDeckPlayer htmlUrl={next} />)
    expect(screen.getByTitle("HTML deck").getAttribute("src")).toBe(next)
  })

  it("opens at the requested slide and keeps it across a re-signed URL", () => {
    const { rerender } = renderWithIntl(<HtmlDeckPlayer htmlUrl={URL_1} slide={{ index: 2, seq: 1 }} />)
    expect(screen.getByTitle("HTML deck").getAttribute("src")).toBe(`${URL_1}#/2`)

    rerender(<HtmlDeckPlayer htmlUrl={URL_1.replace("Signature=1", "Signature=2")} slide={{ index: 2, seq: 1 }} />)
    expect(screen.getByTitle("HTML deck").getAttribute("src")).toBe(`${URL_1}#/2`)
  })

  it("moves a loaded deck with reveal.js's postMessage API, an unloaded one through the URL", () => {
    const { rerender } = renderWithIntl(<HtmlDeckPlayer htmlUrl={URL_1} />)
    const frame = screen.getByTitle("HTML deck") as HTMLIFrameElement

    rerender(<HtmlDeckPlayer htmlUrl={URL_1} slide={{ index: 3, seq: 1 }} />)
    expect(frame.getAttribute("src")).toBe(`${URL_1}#/3`)

    fireEvent.load(frame)
    const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {})
    rerender(<HtmlDeckPlayer htmlUrl={URL_1} slide={{ index: 3, seq: 2 }} />)
    expect(post).toHaveBeenCalledWith(JSON.stringify({ method: "slide", args: [3] }), "*")
    expect(frame.getAttribute("src")).toBe(`${URL_1}#/3`)

    rerender(<HtmlDeckPlayer htmlUrl={URL_1} slide={{ index: 0, seq: 3 }} />)
    expect(post).toHaveBeenLastCalledWith(JSON.stringify({ method: "slide", args: [0] }), "*")
  })
})

describe("deckUrlAtSlide", () => {
  it("adds a reveal.js slide fragment without touching the signed query", () => {
    expect(deckUrlAtSlide(URL_1, 4)).toBe(`${URL_1}#/4`)
    expect(deckUrlAtSlide(`${URL_1}#/4`, 1)).toBe(`${URL_1}#/1`)
    expect(deckUrlAtSlide(`${URL_1}#/4`, 0)).toBe(URL_1)
    expect(deckUrlAtSlide(URL_1, undefined)).toBe(URL_1)
  })
})
