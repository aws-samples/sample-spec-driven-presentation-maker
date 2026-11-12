// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Settings (local): agent selection toasts are translated and a failed save rolls back; the
 * Agents section is translated; the agent engine section is shown even when the agent
 * definitions cannot be listed.
 */

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
  getAgentEngine: vi.fn(),
  setAgentEngine: vi.fn(),
}))

import { getAgentDefinitions, getAgentEngine, listLocalModels, updateAgentSelection } from "@/services/localService"
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
  const trigger = await screen.findByLabelText(locale === "ja" ? "orchestrator エージェントを選択" : "Select orchestrator agent")
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
    vi.mocked(getAgentEngine).mockResolvedValue({ engine: "v2", default: "v3" })
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

describe("Settings (local) — sections", () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("translates the Agents section", async () => {
    vi.mocked(getAgentDefinitions).mockResolvedValue({
      agents: AGENTS,
      selection: { orchestrator: "a.json", composer: "a.json", style: "a.json", translate: "a.json" },
    })
    vi.mocked(listLocalModels).mockResolvedValue([])
    vi.mocked(getAgentEngine).mockResolvedValue({ engine: "v2", default: "v3" })
    renderWithIntl(<Settings open onOpenChange={() => {}} />, { locale: "ja" })
    expect(await screen.findByText("各役割で使うエージェント定義を選択します")).toBeTruthy()
    expect(screen.getByLabelText("orchestrator エージェントを選択")).toBeTruthy()
  })

  it("shows the agent engine even when the agent definitions cannot be listed", async () => {
    vi.mocked(getAgentDefinitions).mockRejectedValue(new Error("HTTP 500"))
    vi.mocked(listLocalModels).mockResolvedValue([])
    vi.mocked(getAgentEngine).mockResolvedValue({ engine: "v3", default: "v3" })
    renderWithIntl(<Settings open onOpenChange={() => {}} />, { locale: "en" })
    const v2 = await screen.findByRole("radio", { name: /^V2 \(previous\)/ })
    expect(v2).toBeTruthy()
    expect(screen.queryByText("Choose which agent definition each role uses.")).toBeNull()
  })
})
