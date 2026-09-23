// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { SessionPickerDialog } from "./SessionPickerDialog"
import type { KiroSessionsResponse } from "@/lib/local/kiro-sessions.types"

vi.mock("@/lib/mode", () => ({
  IS_LOCAL: true,
  LocalOnly: ({ children }: { children: React.ReactNode }) => children,
  CloudOnly: () => null,
}))

const sessions: KiroSessionsResponse = {
  groups: [
    {
      cwd: "/work/alpha",
      project: "alpha",
      sessions: [
        {
          sessionId: "11111111-1111-4111-8111-111111111111",
          title: "Investigate rendering latency",
          cwd: "/work/alpha",
          project: "alpha",
          updatedAt: "2026-09-22T10:00:00.000Z",
          messageCount: 12,
          agentName: null,
        },
        {
          sessionId: "22222222-2222-4222-8222-222222222222",
          title: "Plan migration rollout",
          cwd: "/work/alpha",
          project: "alpha",
          updatedAt: "2026-09-22T09:00:00.000Z",
          messageCount: 4,
          agentName: "kiro",
        },
      ],
    },
  ],
  recent: [],
}

function mockResponse(data: KiroSessionsResponse) {
  vi.mocked(fetch).mockResolvedValue({
    ok: true,
    json: async () => data,
  } as Response)
}

describe("SessionPickerDialog", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn())
    mockResponse(sessions)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it("filters sessions by title as the user types", async () => {
    renderWithIntl(<SessionPickerDialog open onOpenChange={() => {}} onSelect={() => {}} />)

    await screen.findByText("Investigate rendering latency")
    fireEvent.change(screen.getByPlaceholderText("Search sessions…"), {
      target: { value: "migration" },
    })

    expect(screen.getByText("Plan migration rollout")).toBeTruthy()
    expect(screen.queryByText("Investigate rendering latency")).toBeNull()
  })

  it("moves through the list and selects with the keyboard", async () => {
    const onSelect = vi.fn()
    renderWithIntl(<SessionPickerDialog open onOpenChange={() => {}} onSelect={onSelect} />)

    await screen.findByText("Investigate rendering latency")
    const search = screen.getByPlaceholderText("Search sessions…")
    fireEvent.keyDown(search, { key: "ArrowDown" })
    const listbox = screen.getByRole("listbox")
    await waitFor(() => expect(document.activeElement).toBe(listbox))
    fireEvent.keyDown(listbox, { key: "ArrowDown" })
    fireEvent.keyDown(listbox, { key: "Enter" })

    expect(onSelect).toHaveBeenCalledWith(sessions.groups[0].sessions[1])
  })

  it("keeps options out of the tab order and retries a failed load", async () => {
    vi.mocked(fetch)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ ok: true, json: async () => sessions } as Response)
    renderWithIntl(<SessionPickerDialog open onOpenChange={() => {}} onSelect={() => {}} />)

    expect(await screen.findByRole("alert")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))

    const option = await screen.findByRole("option", { name: /Investigate rendering latency/ })
    expect(option.getAttribute("tabindex")).toBe("-1")
  })

  it("shows an empty state with guidance", async () => {
    mockResponse({ groups: [], recent: [] })
    renderWithIntl(<SessionPickerDialog open onOpenChange={() => {}} onSelect={() => {}} />)

    expect(await screen.findByText("No sessions found")).toBeTruthy()
    expect(screen.getByText(/kiro-cli chat/)).toBeTruthy()
  })
})
