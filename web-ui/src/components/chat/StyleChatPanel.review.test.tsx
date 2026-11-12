// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatPanel sending a change request from the style preview: the frames collect in the
 * draft bar, one send turns them and the typed text into the request message (built in the
 * browser, no review file) and takes them off the drafts; a steer the agent did not take puts
 * them back. Without drafts the plain send is unchanged.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"

const { sendMessage, createReview, streamState } = vi.hoisted(() => ({
  sendMessage: vi.fn<(...args: unknown[]) => Promise<boolean>>(async () => true),
  createReview: vi.fn(),
  streamState: { isLoading: false },
}))

vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { id_token: "tok", access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn(), info: vi.fn(), error: vi.fn() }) }))
vi.mock("@/services/agentCoreService", () => ({ generateSessionId: () => "s".repeat(36), setAgentConfig: vi.fn() }))
vi.mock("@/services/localService", () => ({ saveLocalChat: vi.fn(async () => {}) }))
vi.mock("@/services/deckService", () => ({ createReview }))
vi.mock("@/hooks/useChatStream", () => ({
  useChatStream: () => ({
    messages: [], isLoading: streamState.isLoading, stopping: false, reconnecting: false, sendMessage, stopGeneration: vi.fn(),
    steerQueue: [], dismissSteer: vi.fn(), arrivedSteerIds: new Set(),
  }),
}))

import { StyleChatPanel } from "./StyleChatPanel"
import { ReviewProvider, useReview, type ReviewContextValue } from "@/components/review/ReviewProvider"
import { parseReviewMessage } from "@/lib/review/marker"
import { createStyleReview } from "@/lib/review/style"
import type { ReviewSubmission } from "@/lib/review/schema"

const SLIDES = [
  `<div class="slide cover"><div class="el slide-title">Cover</div></div>`,
  `<div class="slide body"><div class="el slide-title">Agenda</div><div class="el">items</div></div>`,
]

let api: ReviewContextValue
const setApi = (value: ReviewContextValue | null) => { api = value as ReviewContextValue }
function Capture() {
  setApi(useReview())
  return null
}

function renderPanel() {
  return renderWithIntl(
    <ReviewProvider
      deckId="style:brand-blue"
      slugs={["1", "2"]}
      enabled
      agentBusy={streamState.isLoading}
      openChat={() => {}}
      createRequest={(s: ReviewSubmission) => Promise.resolve(createStyleReview(s, SLIDES))}
    >
      <Capture />
      <StyleChatPanel styleId="brand-blue" />
    </ReviewProvider>,
  )
}

/** Draw and save a comment, as the canvas and card do. */
function addSaved(slide: string, text: string) {
  act(() => { api.addFrame(slide, [10.4, 20.6, 300, 200]) })
  act(() => { api.setEditorText(text) })
  act(() => { api.closeEditor(true) })
}

const textbox = () => screen.getByRole("textbox") as HTMLTextAreaElement
const sendButton = () => screen.getByRole("button", { name: "Request changes" }) as HTMLButtonElement
const firstSent = () => (sendMessage.mock.calls[0] as unknown[])[0] as string

async function requestChanges(note: string) {
  fireEvent.change(textbox(), { target: { value: note } })
  await act(async () => { fireEvent.click(sendButton()) })
}

describe("StyleChatPanel change request", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    streamState.isLoading = false
    sendMessage.mockResolvedValue(true)
    Element.prototype.scrollIntoView = vi.fn()
  })
  afterEach(() => { cleanup() })

  it("sends a plain message unchanged without drafts", async () => {
    const { container } = renderPanel()
    expect(container.querySelector("[data-review-draft-bar]")).toBeNull()
    fireEvent.change(textbox(), { target: { value: "hi" } })
    await act(async () => { fireEvent.submit(textbox().closest("form")!) })
    expect(firstSent()).toBe("[Style: brand-blue]\n\nhi")
  })

  it("sends the frames and the typed text as one request message", async () => {
    const { container } = renderPanel()
    addSaved("2", "bigger")
    expect(container.querySelector("[data-review-draft-bar]")).not.toBeNull()
    await requestChanges("overall")

    const sent = firstSent()
    expect(sent.startsWith("[Style: brand-blue]\n\n[review:")).toBe(true)
    expect(parseReviewMessage(sent)).toMatchObject({
      note: "overall",
      comments: [{ name: "A", slide: "2", rect: [10, 21, 300, 200], text: "bigger" }],
    })
    expect(sent).toContain(`"title":"Agenda"`)
    expect(api.drafts).toEqual([])
    await waitFor(() => expect(container.querySelector("[data-review-draft-bar]")).toBeNull())
    expect(createReview).not.toHaveBeenCalled()
  })

  it("cannot send a frame without a comment until a message is typed", () => {
    const { container } = renderPanel()
    addSaved("1", "")
    expect(sendButton().disabled).toBe(true)
    expect(container.querySelector("[data-review-needs-text]")).not.toBeNull()
    fireEvent.change(textbox(), { target: { value: "make @A the title" } })
    expect(sendButton().disabled).toBe(false)
  })

  it("puts the frames back when the agent does not take the steer", async () => {
    streamState.isLoading = true
    sendMessage.mockImplementation(async (...args: unknown[]) => {
      (args[4] as { onSteerFailed?: () => void } | undefined)?.onSteerFailed?.()
      return false
    })
    renderPanel()
    addSaved("2", "bigger")
    await requestChanges("overall")

    expect(sendMessage).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(api.drafts.map(d => [d.name, d.slide, d.text])).toEqual([["A", "2", "bigger"]]))
    await waitFor(() => expect(textbox().value).toBe("overall"))
  })
})
