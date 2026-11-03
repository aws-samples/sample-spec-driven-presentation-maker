// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Settings (local): agent selection toasts are translated and a failed save rolls back. */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { toast } from "sonner"
import { renderWithIntl } from "@/test/renderWithIntl"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: true }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock("@/services/localService", () => ({
  getAgentDefinitions: vi.fn(),
  listLocalModels: vi.fn(),
  updateAgentSelection: vi.fn(),
}))

import { getAgentDefinitions, listLocalModels, updateAgentSelection } from "@/services/localService"
import { Settings } from "./Settings"

// jsdom has no scrollIntoView; cmdk and ModelPicker call it.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

const AGENTS = [
  { fileName: "a.json", name: "Agent A", description: "" },
  { fileName: "b.json", name: "Agent B", description: "" },
]

async function pickOrchestrator(locale: "en" | "ja") {
  renderWithIntl(<Settings open onOpenChange={() => {}} />, { locale })
  const trigger = await screen.findByLabelText("Select orchestrator agent")
  await waitFor(() => expect(trigger.textContent).toContain("Agent A"))
  fireEvent.click(trigger)
  fireEvent.click(screen.getByRole("option", { name: /Agent B/ }))
  return trigger
}

describe("Settings (local) — agent selection", () => {
  beforeEach(() => {
    vi.mocked(getAgentDefinitions).mockResolvedValue({
      agents: AGENTS,
      selection: { orchestrator: "a.json", composer: "a.json", style: "a.json", translate: "a.json" },
    })
    vi.mocked(listLocalModels).mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("shows the translated toast after saving", async () => {
    vi.mocked(updateAgentSelection).mockResolvedValue(undefined)
    const trigger = await pickOrchestrator("ja")
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(
      "orchestrator エージェントを更新しました",
      { description: "Agent B を使用します。次のチャットから反映され、現在のチャットには影響しません。" },
    ))
    expect(updateAgentSelection).toHaveBeenCalledWith({ orchestrator: "b.json" })
    expect(trigger.textContent).toContain("Agent B")
  })

  it("rolls the selection back and shows the translated error when the save fails", async () => {
    vi.mocked(updateAgentSelection).mockRejectedValue(new Error("HTTP 500"))
    const trigger = await pickOrchestrator("ja")
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("orchestrator エージェントを更新できませんでした"))
    expect(toast.success).not.toHaveBeenCalled()
    await waitFor(() => expect(trigger.textContent).toContain("Agent A"))
  })
})
