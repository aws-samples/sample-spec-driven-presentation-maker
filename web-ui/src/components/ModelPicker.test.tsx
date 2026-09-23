// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect, afterEach, beforeAll, vi } from "vitest"
import { screen, fireEvent, cleanup } from "@testing-library/react"
import { renderWithIntl as render } from "@/test/renderWithIntl"
import { ModelPicker } from "./ModelPicker"
import type { AllowedModel } from "@/lib/allowedModels"

// jsdom has no scrollIntoView; both cmdk (on selection) and the picker (after
// opening) call it.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

const flat: AllowedModel[] = [
  { modelId: "m-a", displayName: "Model A" },
  { modelId: "m-b", displayName: "Model B" },
  { modelId: "m-c", displayName: "Model C" },
]

const grouped: AllowedModel[] = [
  { modelId: "m-a", displayName: "Model A", recommended: true },
  { modelId: "m-b", displayName: "Model B" },
  { modelId: "m-c", displayName: "Model C", recommended: true },
  { modelId: "m-d", displayName: "Model D" },
]

function open() {
  fireEvent.click(screen.getByRole("combobox"))
}

describe("ModelPicker", () => {
  afterEach(cleanup)

  it("renders a flat list when no model is recommended", () => {
    render(<ModelPicker models={flat} value="m-a" onChange={() => {}} />)
    open()
    expect(screen.queryByText("Recommended")).toBeNull()
    expect(screen.queryByText("Other models")).toBeNull()
    expect(screen.getAllByRole("option")).toHaveLength(3)
  })

  it("splits recommended and other models into two groups, keeping config order", () => {
    render(<ModelPicker models={grouped} value="m-a" onChange={() => {}} />)
    open()
    expect(screen.getByText("Recommended")).toBeDefined()
    expect(screen.getByText("Other models")).toBeDefined()
    const names = screen.getAllByRole("option").map((o) => o.textContent)
    expect(names).toEqual(["Model A", "Model C", "Model B", "Model D"])
  })

  it("marks the default model with a Default badge, not Recommended", () => {
    render(<ModelPicker models={grouped} value="m-c" defaultId="m-c" onChange={() => {}} />)
    // Trigger shows the badge for the selected default.
    expect(screen.getAllByLabelText("Default").length).toBeGreaterThan(0)
    open()
    // Exactly one option carries the badge (the default), and "Recommended" is
    // only the group heading — never a per-model badge.
    const options = screen.getAllByRole("option")
    const badged = options.filter((o) => o.textContent?.includes("Default"))
    expect(badged).toHaveLength(1)
    expect(badged[0].textContent).toContain("Model C")
    expect(screen.getAllByText("Recommended")).toHaveLength(1)
  })

  it("selecting an item in the Other group calls onChange", () => {
    const onChange = vi.fn()
    render(<ModelPicker models={grouped} value="m-a" onChange={onChange} />)
    open()
    fireEvent.click(screen.getByText("Model D"))
    expect(onChange).toHaveBeenCalledWith("m-d")
  })
})
