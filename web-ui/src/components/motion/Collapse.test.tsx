// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { Collapse } from "./Collapse"

afterEach(cleanup)

describe("Collapse", () => {
  it("shows its children while shown", () => {
    render(<Collapse show>hello</Collapse>)
    expect(screen.getByText("hello")).toBeTruthy()
  })

  it("removes them at once where nothing can animate, and shows them again at once", () => {
    const view = render(<Collapse show>hello</Collapse>)
    view.rerender(<Collapse show={false}>hello</Collapse>)
    expect(screen.queryByText("hello")).toBeNull()
    view.rerender(<Collapse show>hello</Collapse>)
    expect(screen.getByText("hello")).toBeTruthy()
  })

  it("renders nothing when it starts hidden", () => {
    render(<Collapse show={false}>hello</Collapse>)
    expect(screen.queryByText("hello")).toBeNull()
  })
})
