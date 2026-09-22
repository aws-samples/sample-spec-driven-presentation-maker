// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen } from "@testing-library/react"

import { renderWithIntl } from "@/test/renderWithIntl"
import type { ForkSessionPhase, KiroSessionSummary } from "@/lib/local/kiro-sessions.types"
import { ForkProgressCard } from "./ForkProgressCard"

const session: KiroSessionSummary = {
  sessionId: "11111111-1111-4111-8111-111111111111",
  title: "Investigate rendering latency",
  cwd: "/work/alpha",
  project: "alpha",
  updatedAt: "2026-09-22T10:00:00.000Z",
  messageCount: 12,
  agentName: null,
}

const expectedStates: Record<ForkSessionPhase, string[]> = {
  copying: ["active", "pending", "pending", "pending"],
  starting: ["completed", "active", "pending", "pending"],
  loading: ["completed", "completed", "active", "pending"],
  switching: ["completed", "completed", "completed", "active"],
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("ForkProgressCard", () => {
  it("shows the session summary and advances through every phase", () => {
    const { container, rerender } = renderWithIntl(
      <ForkProgressCard session={session} phase="copying" replayed={0} onCancel={() => {}} />,
    )

    expect(screen.getByText("Investigate rendering latency")).toBeTruthy()
    expect(screen.getByText("alpha · 12 messages")).toBeTruthy()

    for (const phase of Object.keys(expectedStates) as ForkSessionPhase[]) {
      rerender(<ForkProgressCard session={session} phase={phase} replayed={47} onCancel={() => {}} />)
      expect(Array.from(container.querySelectorAll("ol li")).map((item) => item.getAttribute("data-state")))
        .toEqual(expectedStates[phase])
      if (phase === "loading") expect(screen.getByText("Loading conversation… 47 updates")).toBeTruthy()
    }

    expect(screen.getByRole("status").textContent).toBe("Prepare slide creation")
  })

  it("invokes cancel and reveals the long-session hint after eight seconds", () => {
    vi.useFakeTimers()
    const onCancel = vi.fn()
    renderWithIntl(<ForkProgressCard session={session} phase="loading" replayed={20} onCancel={onCancel} />)

    expect(screen.queryByText("Long sessions can take tens of seconds to load.")).toBeNull()
    act(() => vi.advanceTimersByTime(8000))
    expect(screen.getByText("Long sessions can take tens of seconds to load.")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(onCancel).toHaveBeenCalledOnce()
  })
})
