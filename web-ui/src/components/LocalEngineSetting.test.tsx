// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Settings → Agent engine: shows the engine read when the sheet opens, saves a choice with a
 * translated toast, puts the previous choice back when the save fails, and reports a failed read.
 */

import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { toast } from "sonner"
import { renderWithIntl } from "@/test/renderWithIntl"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock("@/services/localService", () => ({ getAgentEngine: vi.fn(), setAgentEngine: vi.fn() }))

import { getAgentEngine, setAgentEngine } from "@/services/localService"
import { LocalEngineSetting } from "./LocalEngineSetting"

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const radio = (name: RegExp) => screen.getByRole("radio", { name })

describe("LocalEngineSetting", () => {
  it("shows the configured engine and saves another one with a toast", async () => {
    vi.mocked(getAgentEngine).mockResolvedValue({ engine: "v2", default: "v2" })
    vi.mocked(setAgentEngine).mockResolvedValue(undefined)
    renderWithIntl(<LocalEngineSetting open />, { locale: "ja" })
    await waitFor(() => expect(radio(/^V2/).getAttribute("aria-checked")).toBe("true"))
    expect(radio(/^V3（推奨）/).getAttribute("aria-checked")).toBe("false")

    fireEvent.click(radio(/^V3/))
    expect(setAgentEngine).toHaveBeenCalledWith("v3")
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("エージェントエンジン: V3（推奨）", { description: "次のメッセージから反映されます。" }))
    expect(radio(/^V3/).getAttribute("aria-checked")).toBe("true")
  })

  it("does not save the engine already chosen", async () => {
    vi.mocked(getAgentEngine).mockResolvedValue({ engine: "v3", default: "v2" })
    renderWithIntl(<LocalEngineSetting open />)
    await waitFor(() => expect(radio(/^V3/).getAttribute("aria-checked")).toBe("true"))
    fireEvent.click(radio(/^V3/))
    expect(setAgentEngine).not.toHaveBeenCalled()
  })

  it("puts the previous engine back when the save fails", async () => {
    vi.mocked(getAgentEngine).mockResolvedValue({ engine: "v3", default: "v2" })
    vi.mocked(setAgentEngine).mockRejectedValue(new Error("HTTP 500"))
    renderWithIntl(<LocalEngineSetting open />)
    await waitFor(() => expect(radio(/^V3/).getAttribute("aria-checked")).toBe("true"))
    fireEvent.click(radio(/^V2 \(previous\)/))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to change the agent engine"))
    expect(radio(/^V3/).getAttribute("aria-checked")).toBe("true")
    expect(radio(/^V2/).getAttribute("aria-checked")).toBe("false")
  })

  it("reads nothing while the sheet is closed, and reports a failed read", async () => {
    vi.mocked(getAgentEngine).mockRejectedValue(new Error("HTTP 500"))
    const { rerender } = renderWithIntl(<LocalEngineSetting open={false} />)
    expect(getAgentEngine).not.toHaveBeenCalled()
    rerender(<LocalEngineSetting open />)
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe("Failed to load the agent engine setting")
  })
})
