// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { StrictMode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, waitFor } from "@testing-library/react"
import { AnimatedSlidePreview } from "./AnimatedSlidePreview"
import { resetAnimationSchedulerForTests } from "./animationScheduler"

const defs = { version: 1, defs: "<defs />" }
const compose = {
  version: 1,
  viewBox: "0 0 1920 1080",
  bgFill: "#000",
  bgSvg: null,
  components: [{
    class: "Graphic",
    bbox: { x: 200, y: 200, w: 300, h: 300 },
    text: "",
    svg: '<rect x="200" y="200" width="300" height="300" />',
    changed: false,
  }],
}

beforeEach(() => {
  resetAnimationSchedulerForTests()
  vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
    const data = String(input).includes("defs") ? defs : compose
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: true, media: "", onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })))
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("AnimatedSlidePreview under React Strict Mode", () => {
  // Strict Mode mounts → unmounts → remounts effects. The first fetch is aborted by
  // the cleanup; the remount must fetch again instead of trusting refs that say the
  // URL was already handled (which left existing decks as blank black cards in dev).
  it("renders the slide after the dev-mode effect remount", async () => {
    const { container } = render(
      <StrictMode>
        <AnimatedSlidePreview defsUrl="/defs.json" composeUrl="/compose.json" slug="s1" />
      </StrictMode>,
    )

    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull())
    const composeCalls = vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/compose.json")
    expect(composeCalls.length).toBeGreaterThanOrEqual(1)
  })
})
