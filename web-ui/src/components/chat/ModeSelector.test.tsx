// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { ModeSelector } from "./ModeSelector"
import { renderWithIntl } from "@/test/renderWithIntl"

afterEach(cleanup)

describe("ModeSelector", () => {
  it("presents Vibe and Spec as two readable working styles", () => {
    renderWithIntl(<ModeSelector value="spec" onChange={() => {}} />)

    expect(screen.getByText("Choose your working style")).toBeTruthy()
    expect(screen.getByText("Fast path")).toBeTruthy()
    expect(screen.getByText("Review path")).toBeTruthy()
    expect(screen.getByText("Start rough. See a first draft sooner.")).toBeTruthy()
    expect(screen.getByText("Decide the story before the slides.")).toBeTruthy()
  })

  it("exposes the selected mode with aria-pressed", () => {
    renderWithIntl(<ModeSelector value="spec" onChange={() => {}} />)

    expect(screen.getByRole("button", { name: /Vibe/ }).getAttribute("aria-pressed")).toBe("false")
    expect(screen.getByRole("button", { name: /Spec/ }).getAttribute("aria-pressed")).toBe("true")
  })

  it("changes mode when a row is selected", () => {
    const onChange = vi.fn()
    renderWithIntl(<ModeSelector value="spec" onChange={onChange} />)

    fireEvent.click(screen.getByRole("button", { name: /Vibe/ }))
    expect(onChange).toHaveBeenCalledWith("vibe")
  })

  it("uses full-row touch targets", () => {
    renderWithIntl(<ModeSelector value="vibe" onChange={() => {}} />)

    expect(screen.getByRole("button", { name: /Vibe/ }).className).toContain("min-h-[82px]")
    expect(screen.getByRole("button", { name: /Spec/ }).className).toContain("min-h-[82px]")
  })

  it("does not render the old Great for detail list", () => {
    renderWithIntl(<ModeSelector value="spec" onChange={() => {}} />)

    expect(screen.queryByText("Great for")).toBeNull()
    expect(screen.queryByText("Proposals & pitch decks")).toBeNull()
  })
})
