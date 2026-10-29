// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { HtmlFormatPill } from "./HtmlFormatPill"

afterEach(cleanup)

const HINT = "Creates an HTML deck to present in a browser. It can't be edited in PowerPoint."

describe("HtmlFormatPill", () => {
  it("is not pressed without the token and turns it on", () => {
    const onChange = vi.fn()
    renderWithIntl(<HtmlFormatPill text="a launch deck" onChange={onChange} />)

    const pill = screen.getByRole("button", { name: "Build as HTML" })
    expect(pill.getAttribute("aria-pressed")).toBe("false")
    expect(pill.getAttribute("title")).toBe(HINT)
    fireEvent.click(pill)
    expect(onChange).toHaveBeenCalledWith("@format:html a launch deck")
  })

  it("is pressed exactly when the input holds @format:html and turns it off", () => {
    const onChange = vi.fn()
    renderWithIntl(<HtmlFormatPill text="@format:html a launch deck" onChange={onChange} />)

    const pill = screen.getByRole("button", { name: "Build as HTML" })
    expect(pill.getAttribute("aria-pressed")).toBe("true")
    fireEvent.click(pill)
    expect(onChange).toHaveBeenCalledWith("a launch deck")
  })
})
