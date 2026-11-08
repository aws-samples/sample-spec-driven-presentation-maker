// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * LocalModelPicker: hidden while no model list is known or the list cannot be read; the pill
 * shows the chat's live model and effort, a held choice first, or "Default model" / "This chat's
 * model" before kiro-cli reported one; the menu lists the models and, for a model with effort
 * levels only, those levels; a choice is sent and a refused one restores the pill with a toast;
 * Japanese labels; the list is read again when a turn ends.
 */

import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { LocalSessionModels } from "@/services/localService"

vi.mock("@/services/localService", () => ({ getLocalSessionModels: vi.fn(), setLocalSessionModel: vi.fn() }))
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))

import { toast } from "sonner"
import { getLocalSessionModels, setLocalSessionModel } from "@/services/localService"
import { LocalModelPicker } from "./LocalModelPicker"

const AVAILABLE = [
  { modelId: "auto", name: "Auto", rate: 1 },
  { modelId: "claude-haiku-5.5", name: "Claude Haiku 5.5", effortLevels: ["low", "medium", "max"], defaultEffort: "medium", rate: 0.06 },
  { modelId: "claude-haiku-4.5", name: "Claude Haiku 4.5" },
]

const view = (over: Partial<LocalSessionModels> = {}): LocalSessionModels => ({ engine: "v3", available: AVAILABLE, current: null, pending: null, ...over })

const trigger = () => screen.getByRole("button", { name: /Model:|モデル:/ })
const open = () => fireEvent.keyDown(trigger(), { key: "Enter" })

function render(props: Partial<Parameters<typeof LocalModelPicker>[0]> = {}, locale: "en" | "ja" = "en") {
  return renderWithIntl(<LocalModelPicker sessionId="S1" isNewChat={false} busy={false} {...props} />, { locale })
}

afterEach(cleanup)

beforeEach(() => {
  vi.mocked(getLocalSessionModels).mockReset()
  vi.mocked(setLocalSessionModel).mockReset()
  vi.mocked(toast.error).mockReset()
})

describe("LocalModelPicker", () => {
  it("renders nothing while no list is known, or when it cannot be read", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ available: [] }))
    const { container, unmount } = render()
    await waitFor(() => expect(getLocalSessionModels).toHaveBeenCalledWith("S1"))
    expect(container.innerHTML).toBe("")
    unmount()

    vi.mocked(getLocalSessionModels).mockRejectedValueOnce(new Error("HTTP 500"))
    const failed = render()
    await waitFor(() => expect(getLocalSessionModels).toHaveBeenCalledTimes(2))
    expect(failed.container.innerHTML).toBe("")
    expect(toast.error).not.toHaveBeenCalled()
  })

  it("shows the live model and effort, a held choice first, and a placeholder before kiro-cli reported one", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ current: { model: "claude-haiku-5.5", effort: "low", effortLevels: ["low", "medium", "max"] } }))
    const live = render()
    expect(await screen.findByText("Claude Haiku 5.5 · Low")).toBeTruthy()
    expect(trigger().getAttribute("aria-label")).toBe("Model: Claude Haiku 5.5, effort: Low")
    live.unmount()

    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ current: { model: "auto", effort: null, effortLevels: [] }, pending: { model: "claude-haiku-5.5" } }))
    const held = render()
    expect(await screen.findByText("Claude Haiku 5.5 · Medium")).toBeTruthy()
    held.unmount()

    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view())
    const fresh = render({ isNewChat: true })
    expect(await screen.findByText("Default model")).toBeTruthy()
    fresh.unmount()

    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view())
    render()
    expect(await screen.findByText("This chat's model")).toBeTruthy()
  })

  it("lists the models with their rate, and the effort levels only for a model that has them", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ current: { model: "auto", effort: null, effortLevels: [] } }))
    render()
    await screen.findByText("Auto")
    open()
    expect(await screen.findByRole("menuitemradio", { name: /Claude Haiku 5\.5/ })).toBeTruthy()
    expect(screen.getByText("0.06× credits")).toBeTruthy()
    expect(screen.queryByText("Effort")).toBeNull()
    expect(screen.getByText("Applies from your next message.")).toBeTruthy()
  })

  it("sends a model choice and shows what the server answered", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ current: { model: "auto", effort: null, effortLevels: [] } }))
    vi.mocked(setLocalSessionModel).mockResolvedValueOnce(view({ current: { model: "claude-haiku-5.5", effort: "medium", effortLevels: ["low", "medium", "max"] } }))
    render()
    await screen.findByText("Auto")
    open()
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Claude Haiku 5\.5/ }))
    expect(setLocalSessionModel).toHaveBeenCalledWith("S1", { model: "claude-haiku-5.5" })
    expect(await screen.findByText("Claude Haiku 5.5 · Medium")).toBeTruthy()

    open()
    expect(await screen.findByText("Effort")).toBeTruthy()
    vi.mocked(setLocalSessionModel).mockResolvedValueOnce(view({ current: { model: "claude-haiku-5.5", effort: "max", effortLevels: ["low", "medium", "max"] } }))
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Max" }))
    expect(setLocalSessionModel).toHaveBeenLastCalledWith("S1", { effort: "max" })
    expect(await screen.findByText("Claude Haiku 5.5 · Max")).toBeTruthy()
  })

  it("restores the pill and toasts when the choice is refused", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ current: { model: "auto", effort: null, effortLevels: [] } }))
    vi.mocked(setLocalSessionModel).mockRejectedValueOnce(new Error("HTTP 502"))
    render()
    await screen.findByText("Auto")
    open()
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Claude Haiku 4\.5/ }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't change the model"))
    expect(screen.getByText("Auto")).toBeTruthy()
  })

  it("uses the Japanese labels", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValueOnce(view({ current: { model: "claude-haiku-5.5", effort: "max", effortLevels: ["low", "medium", "max"] } }))
    render({}, "ja")
    expect(await screen.findByText("Claude Haiku 5.5 · 最大")).toBeTruthy()
    expect(trigger().getAttribute("aria-label")).toBe("モデル: Claude Haiku 5.5、思考の深さ: 最大")
    open()
    expect(await screen.findByText("思考の深さ")).toBeTruthy()
    expect(screen.getByText("次のメッセージから使われます。")).toBeTruthy()
  })

  it("reads the list again when a turn ends", async () => {
    vi.mocked(getLocalSessionModels).mockResolvedValue(view())
    const { rerender } = render({ busy: true })
    await waitFor(() => expect(getLocalSessionModels).toHaveBeenCalledTimes(1))
    vi.mocked(getLocalSessionModels).mockResolvedValue(view({ current: { model: "auto", effort: null, effortLevels: [] } }))
    await act(async () => { rerender(<LocalModelPicker sessionId="S1" isNewChat={false} busy={false} />) })
    await waitFor(() => expect(getLocalSessionModels).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("Auto")).toBeTruthy()
  })
})
