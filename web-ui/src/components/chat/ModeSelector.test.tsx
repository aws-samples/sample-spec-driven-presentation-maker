// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it, vi } from "vitest"
import { fireEvent, screen } from "@testing-library/react"
import { ModeSelector } from "./ModeSelector"
import { renderWithIntl } from "@/test/renderWithIntl"

const chip = () => screen.getByRole("button", { name: /Working style/ })
const open = () => fireEvent.keyDown(chip(), { key: "Enter" })

describe("ModeSelector", () => {
  it("names the current working style on the chip", () => {
    renderWithIntl(<ModeSelector value="spec" onChange={() => {}} />)

    expect(chip().getAttribute("aria-label")).toBe("Working style: Spec")
    expect(chip().textContent).toContain("Spec")
  })

  it("explains both working styles in its menu", async () => {
    renderWithIntl(<ModeSelector value="spec" onChange={() => {}} />)
    open()

    expect(await screen.findByText("Choose your working style")).toBeTruthy()
    expect(screen.getByText("Fast path")).toBeTruthy()
    expect(screen.getByText("Review path")).toBeTruthy()
    expect(screen.getByText("Start rough. See a first draft sooner.")).toBeTruthy()
    expect(screen.getByText("Decide the story before the slides.")).toBeTruthy()
  })

  it("marks the selected style in the menu", async () => {
    renderWithIntl(<ModeSelector value="spec" onChange={() => {}} />)
    open()

    expect((await screen.findByRole("menuitemradio", { name: /Spec/ })).getAttribute("aria-checked")).toBe("true")
    expect(screen.getByRole("menuitemradio", { name: /Vibe/ }).getAttribute("aria-checked")).toBe("false")
  })

  it("changes mode when a style is chosen", async () => {
    const onChange = vi.fn()
    renderWithIntl(<ModeSelector value="spec" onChange={onChange} />)
    open()

    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Vibe/ }))
    expect(onChange).toHaveBeenCalledWith("vibe")
  })
})
