// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, it, expect, vi, beforeEach } from "vitest"

const toastError = vi.fn()
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }))

import { notifyError } from "./errors"

describe("notifyError", () => {
  beforeEach(() => {
    toastError.mockClear()
    vi.spyOn(console, "error").mockImplementation(() => {})
  })

  it("shows a toast with the message", () => {
    notifyError("Failed to save", new Error("boom"))
    expect(toastError).toHaveBeenCalledWith("Failed to save", undefined)
  })

  it("logs the original error to the console", () => {
    const err = new Error("boom")
    notifyError("Failed to save", err)
    expect(console.error).toHaveBeenCalledWith("Failed to save", err)
  })

  it("attaches a Retry action when retry is provided", () => {
    const retry = vi.fn()
    notifyError("Failed to open", new Error("x"), { retry })
    const opts = toastError.mock.calls[0][1] as { action: { label: string; onClick: () => void } }
    expect(opts.action.label).toBe("Retry")
    opts.action.onClick()
    expect(retry).toHaveBeenCalled()
  })
})
