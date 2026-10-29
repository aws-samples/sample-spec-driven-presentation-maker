// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { HtmlDeckPlayer } from "./HtmlDeckPlayer"

afterEach(cleanup)

const URL_1 = "https://bucket.s3.ap-northeast-1.amazonaws.com/html/d1/abc.html?X-Amz-Signature=1"

describe("HtmlDeckPlayer", () => {
  it("isolates the deck: exact sandbox and allow attributes, never allow-same-origin", () => {
    renderWithIntl(<HtmlDeckPlayer htmlUrl={URL_1} deckName="Launch" />)

    const frame = screen.getByTitle("HTML deck: Launch") as HTMLIFrameElement
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-popups")
    expect(frame.getAttribute("allow")).toBe("fullscreen *")
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer")
    expect(frame.getAttribute("src")).toBe(URL_1)
    const tokens = frame.getAttribute("sandbox")!.split(/\s+/)
    expect(tokens).not.toContain("allow-same-origin")
    expect(tokens).not.toContain("allow-modals")
    expect(tokens).not.toContain("allow-popups-to-escape-sandbox")
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
})
