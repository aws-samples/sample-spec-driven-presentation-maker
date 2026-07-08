// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { screen, fireEvent, cleanup } from "@testing-library/react"
import { renderWithIntl as render } from "@/test/renderWithIntl"
import { useState } from "react"
import { ErrorBoundary } from "./ErrorBoundary"

function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("kaboom")
  return <div>content alive</div>
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {})
  })
  afterEach(cleanup)

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>
    )
    expect(screen.getByText("content alive")).toBeDefined()
  })

  it("shows fallback with label and error message on crash", () => {
    render(
      <ErrorBoundary label="Chat">
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    )
    expect(screen.getByText("Chat ran into a problem.")).toBeDefined()
    expect(screen.getByText("kaboom")).toBeDefined()
    expect(screen.getByRole("button", { name: /try again/i })).toBeDefined()
  })

  it("recovers when Try again is clicked and the cause is fixed", () => {
    function Harness() {
      const [broken, setBroken] = useState(true)
      return (
        <>
          <button onClick={() => setBroken(false)}>fix</button>
          <ErrorBoundary>
            <Bomb shouldThrow={broken} />
          </ErrorBoundary>
        </>
      )
    }
    render(<Harness />)
    expect(screen.getByText(/ran into a problem/)).toBeDefined()
    fireEvent.click(screen.getByText("fix"))
    fireEvent.click(screen.getByRole("button", { name: /try again/i }))
    expect(screen.getByText("content alive")).toBeDefined()
  })
})
