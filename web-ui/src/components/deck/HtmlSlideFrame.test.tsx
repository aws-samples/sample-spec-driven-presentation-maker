// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
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
})
