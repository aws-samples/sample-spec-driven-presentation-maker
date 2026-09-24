// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { SelectionBar } from "./SelectionBar"

afterEach(cleanup)

describe("SelectionBar", () => {
  it("announces the count and wires the three actions", () => {
    const onSelectAll = vi.fn(), onDelete = vi.fn(), onCancel = vi.fn()
    renderWithIntl(
      <SelectionBar count={2} total={5} progress={null} onSelectAll={onSelectAll} onDelete={onDelete} onCancel={onCancel} />,
    )
    expect(screen.getByText("2 selected")).toBeTruthy()
    fireEvent.click(screen.getByText("Select all (5)"))
    fireEvent.click(screen.getByText("Delete"))
    fireEvent.click(screen.getByLabelText("Cancel selection"))
    expect(onSelectAll).toHaveBeenCalledTimes(1)
    expect(onDelete).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it("disables Delete with nothing selected and Select all when everything is", () => {
    renderWithIntl(
      <SelectionBar count={0} total={3} progress={null} onSelectAll={() => {}} onDelete={() => {}} onCancel={() => {}} />,
    )
    expect((screen.getByText("Delete").closest("button") as HTMLButtonElement).disabled).toBe(true)
    cleanup()
    renderWithIntl(
      <SelectionBar count={3} total={3} progress={null} onSelectAll={() => {}} onDelete={() => {}} onCancel={() => {}} />,
    )
    expect((screen.getByText("Select all (3)").closest("button") as HTMLButtonElement).disabled).toBe(true)
  })

  it("shows progress and locks every action while deleting", () => {
    renderWithIntl(
      <SelectionBar count={4} total={4} progress={{ done: 1, total: 4 }} onSelectAll={() => {}} onDelete={() => {}} onCancel={() => {}} />,
    )
    expect(screen.getByText("Deleting 1 / 4…")).toBeTruthy()
    for (const btn of screen.getAllByRole("button")) expect((btn as HTMLButtonElement).disabled).toBe(true)
  })
})
