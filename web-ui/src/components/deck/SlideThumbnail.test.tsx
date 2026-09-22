// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Tests for aspect-ratio-agnostic slide canvas (Phase 3).
 *
 * Verifies that:
 * 1. SlideThumbnail does NOT use hardcoded aspect-[16/9] or object-cover
 * 2. SlideThumbnail adapts aspect ratio from image natural dimensions
 * 3. AnimatedSlidePreview does NOT use hardcoded aspect-[16/9]
 */

import { describe, it, expect, afterEach, vi } from "vitest"
import { render, cleanup, fireEvent } from "@testing-library/react"
import { SlideThumbnail } from "./SlideThumbnail"

afterEach(cleanup)

describe("SlideThumbnail — aspect ratio agnostic", () => {
  it("does not use hardcoded aspect-[16/9] class", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    const outerDiv = container.firstChild as HTMLElement
    expect(outerDiv.className).not.toContain("aspect-[16/9]")
  })

  it("does not use object-cover on the image", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    const img = container.querySelector("img")
    expect(img).toBeTruthy()
    expect(img!.className).not.toContain("object-cover")
    expect(img!.className).toContain("object-contain")
  })

  it("defaults to 16/9 aspect ratio before image loads", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    const outerDiv = container.firstChild as HTMLElement
    expect(outerDiv.style.aspectRatio).toBe("16/9")
  })

  it("updates aspect ratio from image naturalWidth/naturalHeight on load", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    const img = container.querySelector("img")!

    // jsdom does not set naturalWidth/naturalHeight, so mock them
    Object.defineProperty(img, "naturalWidth", { value: 1920, configurable: true })
    Object.defineProperty(img, "naturalHeight", { value: 1440, configurable: true })

    fireEvent.load(img)

    const outerDiv = container.firstChild as HTMLElement
    expect(outerDiv.style.aspectRatio).toBe("1920/1440")
  })

  it("updates aspect ratio to 16:9 dimensions on load", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    const img = container.querySelector("img")!

    Object.defineProperty(img, "naturalWidth", { value: 1920, configurable: true })
    Object.defineProperty(img, "naturalHeight", { value: 1080, configurable: true })

    fireEvent.load(img)

    const outerDiv = container.firstChild as HTMLElement
    expect(outerDiv.style.aspectRatio).toBe("1920/1080")
  })

  it("maintains absolute inset-0 structure for skeleton contract", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    // Skeleton uses absolute inset-0
    const skeleton = container.querySelector(".slide-skeleton")
    expect(skeleton).toBeTruthy()
    expect(skeleton!.className).toContain("absolute")
    expect(skeleton!.className).toContain("inset-0")

    // Image uses absolute inset-0
    const img = container.querySelector("img")
    expect(img).toBeTruthy()
    expect(img!.className).toContain("absolute")
    expect(img!.className).toContain("inset-0")
  })

  it("does not render image when src is null", () => {
    const { container } = render(
      <SlideThumbnail src={null} alt="slide 1" index={0} />
    )
    expect(container.querySelector("img")).toBeNull()
  })

  it("shows explicit placeholder when src is null instead of skeleton", () => {
    const { container } = render(
      <SlideThumbnail src={null} alt="slide 1" index={0} />
    )
    expect(container.querySelector(".slide-skeleton")).toBeNull()
    expect(container.querySelector("[data-placeholder]")).toBeTruthy()
  })

  it("shows skeleton when src is provided but image has not loaded", () => {
    const { container } = render(
      <SlideThumbnail src="/test.png" alt="slide 1" index={0} />
    )
    expect(container.querySelector(".slide-skeleton")).toBeTruthy()
    expect(container.querySelector("[data-placeholder]")).toBeNull()
  })

  it("calls onError when image fails to load", () => {
    const onError = vi.fn()
    const { container } = render(
      <SlideThumbnail src="/broken.png" alt="slide 1" index={0} onError={onError} />
    )
    const img = container.querySelector("img")!
    fireEvent.error(img)
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it("keeps the old image on screen while a new src loads, then crossfades", () => {
    const { container, rerender } = render(<SlideThumbnail src="/a.png" alt="" index={0} slug="s" />)
    const first = container.querySelector("img[data-shown]") as HTMLImageElement
    fireEvent.load(first)
    expect(container.querySelector(".slide-skeleton")).toBeNull()

    rerender(<SlideThumbnail src="/b.png" alt="" index={0} slug="s" />)
    // Old image still shown, no skeleton, new one loading hidden
    expect((container.querySelector("img[data-shown]") as HTMLImageElement).getAttribute("src")).toBe("/a.png")
    expect(container.querySelector(".slide-skeleton")).toBeNull()
    const incoming = container.querySelector("img[data-incoming]") as HTMLImageElement
    expect(incoming.getAttribute("src")).toBe("/b.png")

    fireEvent.load(incoming)
    expect((container.querySelector("img[data-shown]") as HTMLImageElement).getAttribute("src")).toBe("/b.png")
    expect((container.querySelector("img[data-outgoing]") as HTMLImageElement).getAttribute("src")).toBe("/a.png")
    expect(container.firstElementChild?.className).toContain("slide-updated")
  })

  it("caps the reveal stagger so late slides do not wait", () => {
    const { container } = render(<SlideThumbnail src="/a.png" alt="" index={30} slug="s" />)
    const img = container.querySelector("img[data-shown]") as HTMLImageElement
    expect(img.style.getPropertyValue("--reveal-delay")).toBe("360ms")
  })
})
