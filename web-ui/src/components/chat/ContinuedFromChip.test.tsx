// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ContinuedFromChip } from "./ContinuedFromChip"

const origin = {
  sourceSessionId: "11111111-1111-4111-8111-111111111111",
  title: "Investigate rendering latency",
  cwd: "/work/alpha",
  updatedAt: "2026-09-22T10:00:00.000Z",
  forkedAt: "2026-09-22T11:00:00.000Z",
}

afterEach(cleanup)

describe("ContinuedFromChip", () => {
  it("shows the source title and exposes origin details on focus", async () => {
    renderWithIntl(<ContinuedFromChip origin={origin} />)

    const chip = screen.getByRole("button", { name: "Branched from “Investigate rendering latency”" })
    expect(chip).toBeTruthy()

    fireEvent.focus(chip)
    expect(await screen.findByText("Working directory: /work/alpha")).toBeTruthy()
    expect(screen.getByText("The original session will not be changed.")).toBeTruthy()
  })
})
