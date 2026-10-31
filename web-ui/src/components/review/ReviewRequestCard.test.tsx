// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { ReviewRequest } from "@/lib/review/schema"
import type { ChatMessage as HistoryMessage } from "@/services/deckService"

const { createReview, getReview } = vi.hoisted(() => ({ createReview: vi.fn(), getReview: vi.fn() }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn() }) }))
vi.mock("@/services/deckService", () => ({ createReview, getReview, batchGetSlidePreviewUrls: vi.fn(async () => new Map()) }))

import { ReviewProvider, sentFrameKey, useReview, type ReviewContextValue } from "./ReviewProvider"
import { ReviewRequestCard } from "./ReviewRequestCard"
import { ChatMessage } from "@/components/chat/ChatMessage"
import { parseCloudHistory, parseLocalHistory } from "@/components/chat/chatHistory"

const ID = "20261101-102000-a1b2"

function request(statuses: ("open" | "done")[], replies: (string | null)[] = []): ReviewRequest {
  return {
    version: 1, id: ID, created_at: "2026-11-01T10:20:00Z", note: "直して", slide_size: [1920, 1080],
    comments: statuses.map((status, i) => ({
      name: String.fromCharCode(65 + i), slide: i % 2 ? "sales" : "intro", rect: [0, 0, 100, 100],
      text: `fix ${i}`, refs: [], status, reply: replies[i] ?? null,
    })),
  }
}

let api: ReviewContextValue | null = null
const setApi = (value: ReviewContextValue | null) => { api = value }
function Capture() {
  setApi(useReview())
  return null
}

function withProvider(ui: ReactNode, agentBusy = false) {
  return renderWithIntl(
    <ReviewProvider deckId="d1" slugs={["intro", "sales"]} enabled agentBusy={agentBusy} openChat={vi.fn()} idToken="tok">
      <Capture />
      {ui}
    </ReviewProvider>,
  )
}

describe("ReviewRequestCard", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it("shows progress, replies and slide numbers from the loaded request", async () => {
    getReview.mockResolvedValue(request(["done", "open"], ["Made the logo smaller"]))
    const { container } = withProvider(<ReviewRequestCard reviewId={ID} note="直して" />)
    await waitFor(() => expect(container.querySelector("[data-review-progress]")?.textContent).toBe("1 / 2"))
    expect(screen.getByText("2 comments")).toBeTruthy()
    expect(screen.getByText("Made the logo smaller")).toBeTruthy()
    expect(screen.getByText("Slide 1")).toBeTruthy()
    expect(screen.getByText("Slide 2")).toBeTruthy()
    expect(container.querySelector("[data-review-comment='A']")?.getAttribute("data-status")).toBe("done")
    // Only the open comment jumps to its frame.
    expect(container.querySelector("[data-review-comment='A']")?.getAttribute("role")).toBeNull()
    expect(container.querySelector("[data-review-comment='B']")?.getAttribute("role")).toBe("button")
    expect(getReview).toHaveBeenCalledWith("d1", ID, "tok")
  })

  it("shows a spinner on open comments while the agent works on the latest request", async () => {
    getReview.mockResolvedValue(request(["done", "open"]))
    const { container } = withProvider(<ReviewRequestCard reviewId={ID} note="" />, true)
    await waitFor(() => expect(container.querySelector("[data-review-comment='B'] .animate-spin")).toBeTruthy())
    expect(container.querySelector("[data-review-comment='A'] .animate-spin")).toBeNull()
  })

  it("offers a retry when the request's chat message failed, and the retry resends it", async () => {
    getReview.mockResolvedValue(request(["open"]))
    const { container } = withProvider(<ReviewRequestCard reviewId={ID} note="" />)
    await waitFor(() => expect(container.querySelector("[data-review-comment='A']")).toBeTruthy())
    expect(container.querySelector("[data-review-failed]")).toBeNull()
    const resend = vi.fn()
    act(() => api!.markFailed(ID, resend))
    await waitFor(() => expect(container.querySelector("[data-review-failed]")).toBeTruthy())
    expect(screen.getByText("Couldn't send the change request")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(resend).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(container.querySelector("[data-review-failed]")).toBeNull())
  })

  it("shows Done when every comment is done", async () => {
    getReview.mockResolvedValue(request(["done", "done"]))
    const { container } = withProvider(<ReviewRequestCard reviewId={ID} note="" />)
    await waitFor(() => expect(container.querySelector("[data-review-progress]")?.textContent).toBe("Done"))
  })

  it("shows a muted line when the file cannot be read", async () => {
    getReview.mockResolvedValue(null)
    withProvider(<ReviewRequestCard reviewId={ID} note="直して" />)
    await waitFor(() => expect(screen.getByText("Couldn't read this change request")).toBeTruthy())
    expect(screen.getByText("直して")).toBeTruthy()
  })

  it("renders the note as plain text without a provider", () => {
    renderWithIntl(<ReviewRequestCard reviewId={ID} note="直して" />)
    expect(screen.getByText("Change request")).toBeTruthy()
    expect(screen.getByText("直して")).toBeTruthy()
    expect(getReview).not.toHaveBeenCalled()
  })

  it("does not load another deck's request", () => {
    withProvider(<ReviewRequestCard reviewId={ID} note="直して" deckId="other" />)
    expect(screen.getByText("直して")).toBeTruthy()
    expect(getReview).not.toHaveBeenCalled()
  })
})

describe("ChatMessage with a review marker", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    getReview.mockResolvedValue(request(["open"]))
  })
  afterEach(cleanup)

  it("restores the card from Local history and strips the marker from the note", async () => {
    const [msg] = parseLocalHistory([{ role: "user", content: `直して\n\n[review:${ID}]`, toolUses: [] } as unknown as HistoryMessage])
    const { container } = withProvider(<ChatMessage role={msg.role} content={msg.content} />)
    await waitFor(() => expect(container.querySelector("[data-review-progress]")?.textContent).toBe("0 / 1"))
    expect(getReview).toHaveBeenCalledTimes(1)
    expect(screen.getByText("直して")).toBeTruthy()
    expect(container.textContent).not.toContain("[review:")
  })

  it("restores the card from Cloud history", async () => {
    const parsed = parseCloudHistory([{ role: "user", content: [{ text: `直して\n\n[review:${ID}]` }] } as unknown as HistoryMessage])
    const msg = parsed[0]
    const { container } = withProvider(<ChatMessage role={msg.role} content={msg.content} />)
    await waitFor(() => expect(container.querySelector("[data-review-request-card]")).toBeTruthy())
    await waitFor(() => expect(container.querySelector("[data-review-progress]")?.textContent).toBe("0 / 1"))
    expect(getReview).toHaveBeenCalledTimes(1)
    expect(container.textContent).not.toContain("[review:")
  })

  it("renders a message without markers as the usual bubble", () => {
    const { container } = withProvider(<ChatMessage role="user" content="make it shorter" />)
    expect(screen.getByText("make it shorter")).toBeTruthy()
    expect(container.querySelector("[data-review-request-card]")).toBeNull()
    expect(getReview).not.toHaveBeenCalled()
  })

  it("jumps to an open comment's frame on click", async () => {
    const { container } = withProvider(<ChatMessage role="user" content={`[review:${ID}]`} />)
    await waitFor(() => expect(container.querySelector("[data-review-comment='A']")?.getAttribute("role")).toBe("button"))
    fireEvent.click(container.querySelector("[data-review-comment='A']")!)
    // No canvas here: focusFrame turns the tool on to reveal the frame and selects it.
    expect(api?.selected).toBe(sentFrameKey(ID, "A"))
    expect(api?.toolOn).toBe(true)
  })
})
