// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The 修正依頼 card in the chat is built from the change request message itself (the
 * server's message for the shared fixture), restores from Local and Cloud history, and shows
 * no request status.
 */

import fs from "fs"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { ChatMessage as HistoryMessage } from "@/services/deckService"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn() }) }))
vi.mock("@/services/deckService", () => ({ createReview: vi.fn(), batchGetSlidePreviewUrls: vi.fn(async () => new Map()) }))

import { ReviewProvider, useReview, type ReviewContextValue } from "./ReviewProvider"
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

  it("shows the frame count, the note, the frames with slide numbers, and no status", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} />)
    expect(screen.getByText("4 frames")).toBeTruthy()
    expect(container.textContent).toContain("全体的に文字を減らして")
    expect([...container.querySelectorAll("[data-review-comment]")].map(e => e.getAttribute("data-review-comment"))).toEqual(["A", "C", "B", "D"])
    expect(screen.getAllByText("Slide 2")).toHaveLength(2)
    expect(screen.getAllByText("Slide 1")).toHaveLength(2)
    // D was sent without a comment.
    expect(container.querySelector("[data-review-comment='D']")?.textContent).toContain("No comment")
    expect(screen.queryByText("Done")).toBeNull()
    expect(screen.queryByText("In progress")).toBeNull()
    expect(container.querySelector("[role='button']")).toBeNull()
  })

  it("does not highlight canvas frames from its mentions", () => {
    const { container } = withProvider(<ReviewRequestCard request={REQUEST} />)
    const mention = container.querySelector("[data-mention='B']")!
    fireEvent.mouseEnter(mention)
    expect(api?.highlight).toBeNull()
  })

  it("renders without a provider, with slugs for slide labels", () => {
    renderWithIntl(<ReviewRequestCard request={REQUEST} />)
    expect(screen.getByText("Change request")).toBeTruthy()
    expect(screen.getAllByText("sales")).toHaveLength(2)
  })
})

describe("ChatMessage with a change request", () => {
  beforeEach(() => localStorage.clear())
  afterEach(cleanup)

  it("restores the card from Local history", () => {
    const [msg] = parseLocalHistory([{ role: "user", content: MESSAGE, toolUses: [] } as unknown as HistoryMessage])
    const { container } = withProvider(<ChatMessage role={msg.role} content={msg.content} />)
    expect(container.querySelector("[data-review-request-card]")).toBeTruthy()
    expect(container.textContent).not.toContain("[review:")
    expect(container.textContent).not.toContain("How to handle it")
  })

  it("restores the card from Cloud history", () => {
    const [msg] = parseCloudHistory([{ role: "user", content: [{ text: `<!--sdpm:include_images=true-->\n${MESSAGE}` }] } as unknown as HistoryMessage])
    const { container } = withProvider(<ChatMessage role={msg.role} content={msg.content} />)
    expect(container.querySelector("[data-review-request-card]")).toBeTruthy()
    expect(screen.getByText("4 frames")).toBeTruthy()
    expect(container.textContent).not.toContain("[review:")
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
