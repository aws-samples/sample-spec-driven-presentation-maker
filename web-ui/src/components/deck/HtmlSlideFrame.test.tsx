// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { HtmlSlideFrame } from "./HtmlSlideFrame"

afterEach(cleanup)

describe("HtmlSlideFrame", () => {
  it("renders a fully sandboxed, inert iframe at the canvas size", () => {
    const { container } = render(<HtmlSlideFrame src="/api/preview/d1/preview/intro.html?v=1" title="Slide 1" width={1280} height={720} />)

    const frame = container.querySelector("iframe") as HTMLIFrameElement
    expect(frame.getAttribute("sandbox")).toBe("")
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer")
    expect(frame.getAttribute("loading")).toBe("lazy")
    expect(frame.getAttribute("aria-hidden")).toBe("true")
    expect(frame.getAttribute("tabindex")).toBe("-1")
    expect(frame.className).toContain("pointer-events-none")
    expect(frame.style.width).toBe("1280px")
    expect(frame.style.height).toBe("720px")
    expect(screen.getByRole("img", { name: "Slide 1" })).toBeTruthy()
  })

  it("keeps a loaded document across a new signature; an unloaded frame takes the fresh URL", () => {
    const signed = (sig: string) => `https://b.s3.ap-northeast-1.amazonaws.com/html/d1/preview/intro_1.html?X-Amz-Signature=${sig}`
    const { container, rerender } = render(<HtmlSlideFrame src={signed("1")} title="Slide 1" />)
    const frame = container.querySelector("iframe") as HTMLIFrameElement

    rerender(<HtmlSlideFrame src={signed("2")} title="Slide 1" />)
    expect(frame.getAttribute("src")).toBe(signed("2"))  // not loaded yet (lazy)

    fireEvent.load(frame)
    rerender(<HtmlSlideFrame src={signed("3")} title="Slide 1" />)
    expect(frame.getAttribute("src")).toBe(signed("2"))

    const rebuilt = "https://b.s3.ap-northeast-1.amazonaws.com/html/d1/preview/intro_2.html?X-Amz-Signature=4"
    rerender(<HtmlSlideFrame src={rebuilt} title="Slide 1" />)
    expect(frame.getAttribute("src")).toBe(rebuilt)
  })
})
