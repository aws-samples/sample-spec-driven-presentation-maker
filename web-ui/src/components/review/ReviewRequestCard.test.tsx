// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The 修正依頼 card in the chat is built from the change request message itself (the
 * server's message for the shared fixture), restores from Local and Cloud history, and shows
 * 対応中 while the turn for that message runs, 完了 after.
 */

import fs from "fs"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { ChatMessage as HistoryMessage } from "@/services/deckService"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn() }) }))
vi.mock("@/services/deckService", () => ({ createReview: vi.fn(), batchGetSlidePreviewUrls: vi.fn(async () => new Map()) }))

import { ReviewProvider, sentFrameKey, useReview, type ReviewContextValue } from "./ReviewProvider"
import { ReviewRequestCard } from "./ReviewRequestCard"
import { ChatMessage } from "@/components/chat/ChatMessage"
import { parseCloudHistory, parseLocalHistory } from "@/components/chat/chatHistory"
import { parseReviewMessage } from "@/lib/review/marker"

const fixture = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../tests/fixtures/review_submissions.json"), "utf-8"),
) as { message_case: { id: string; expected_message: string } }
const ID = fixture.message_case.id
const MESSAGE = fixture.message_case.expected_message
const REQUEST = parseReviewMessage(MESSAGE)!

let api: ReviewContextValue | null = null
const setApi = (value: ReviewContextValue | null) => { api = value }
function Capture() {
  setApi(useReview())
  return null
}

function withProvider(ui: ReactNode) {
  return renderWithIntl(
    <ReviewProvider deckId="d1" slugs={["intro", "sales"]} enabled agentBusy={false} openChat={vi.fn()} idToken="tok">
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

  it("shows the count, the note, the comments with slide numbers, and 完了 after the turn", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} working={false} />)
    expect(screen.getByText("3 comments")).toBeTruthy()
    expect(container.textContent).toContain("全体的に文字を減らして")
    expect([...container.querySelectorAll("[data-review-comment]")].map(e => e.getAttribute("data-review-comment"))).toEqual(["A", "C", "B"])
    expect(screen.getAllByText("Slide 2")).toHaveLength(2)
    expect(screen.getByText("Slide 1")).toBeTruthy()
    expect(container.querySelector("[data-review-status]")?.getAttribute("data-review-status")).toBe("done")
    expect(screen.getByText("Done")).toBeTruthy()
  })

  it("shows 対応中 while the turn runs", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} working />)
    expect(container.querySelector("[data-review-status='working'] .animate-spin")).toBeTruthy()
    expect(screen.getByText("In progress")).toBeTruthy()
  })

  it("jumps to a frame that is on the canvas while the request is in progress", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} working />)
    const row = () => container.querySelector("[data-review-comment='A']")!
    expect(row().getAttribute("role")).toBeNull()
    act(() => api!.setWorkingReview("d1", REQUEST))
    expect(row().getAttribute("role")).toBe("button")
    fireEvent.click(row())
    // No canvas here: focusFrame turns the tool on to reveal the frame and selects it.
    expect(api?.selected).toBe(sentFrameKey(ID, "A"))
    expect(api?.toolOn).toBe(true)
  })

  it("offers a retry instead of the status when the message failed, and the retry resends it", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} working={false} />)
    expect(container.querySelector("[data-review-failed]")).toBeNull()
    const resend = vi.fn()
    act(() => api!.markFailed(ID, resend))
    expect(container.querySelector("[data-review-failed]")).toBeTruthy()
    expect(container.querySelector("[data-review-status]")).toBeNull()
    expect(screen.getByText("Couldn't send the change request")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(resend).toHaveBeenCalledTimes(1)
    expect(container.querySelector("[data-review-failed]")).toBeNull()
  })

  it("renders without a provider, with slugs for slide labels", () => {
    renderWithIntl(<ReviewRequestCard request={REQUEST} working={false} />)
    expect(screen.getByText("Change request")).toBeTruthy()
    expect(screen.getAllByText("sales")).toHaveLength(2)
  })

  it("does not link another deck's request to the canvas", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} working deckId="other" />)
    act(() => api!.setWorkingReview("d1", REQUEST))
    expect(container.querySelector("[data-review-comment='A']")?.getAttribute("role")).toBeNull()
  })
})

describe("ChatMessage with a change request", () => {
  beforeEach(() => localStorage.clear())
  afterEach(cleanup)

  it("restores the card from Local history", () => {
    const [msg] = parseLocalHistory([{ role: "user", content: MESSAGE, toolUses: [] } as unknown as HistoryMessage])
    const { container } = withProvider(<ChatMessage role={msg.role} content={msg.content} />)
    expect(container.querySelector("[data-review-request-card]")).toBeTruthy()
    expect(screen.getByText("Done")).toBeTruthy()
    expect(container.textContent).not.toContain("[review:")
    expect(container.textContent).not.toContain("How to handle it")
  })

  it("restores the card from Cloud history", () => {
    const [msg] = parseCloudHistory([{ role: "user", content: [{ text: `<!--sdpm:include_images=true-->\n${MESSAGE}` }] } as unknown as HistoryMessage])
    const { container } = withProvider(<ChatMessage role={msg.role} content={msg.content} />)
    expect(container.querySelector("[data-review-request-card]")).toBeTruthy()
    expect(screen.getByText("3 comments")).toBeTruthy()
    expect(container.textContent).not.toContain("[review:")
  })

  it("shows 対応中 while the turn for the message runs", () => {
    const { container } = withProvider(<ChatMessage role="user" content={MESSAGE} reviewWorking />)
    expect(container.querySelector("[data-review-status='working']")).toBeTruthy()
  })

  it("renders an ordinary message, or a marker without the request, as the usual bubble", () => {
    const { container } = withProvider(<ChatMessage role="user" content="make it shorter" />)
    expect(screen.getByText("make it shorter")).toBeTruthy()
    expect(container.querySelector("[data-review-request-card]")).toBeNull()
    cleanup()
    const second = withProvider(<ChatMessage role="user" content={`[review:${ID}] 直して`} />)
    expect(second.container.querySelector("[data-review-request-card]")).toBeNull()
  })
})
