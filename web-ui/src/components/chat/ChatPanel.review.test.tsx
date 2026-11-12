// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel sending a change request (Local mode): the sent frames leave the drafts as soon as
 * the request is created and the card shows no status; a turn that fails puts the frames back
 * into the drafts and the typed message back into the input. Frames without a comment can be
 * sent when another frame has one or a message is typed; until then the draft bar says so, and
 * the input keeps its normal placeholder.
 */

import fs from "fs"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"

const { invokeAgentCore, createReview, getChatHistory } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(),
  createReview: vi.fn(),
  getChatHistory: vi.fn(),
}))

vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { id_token: "tok", access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn(), info: vi.fn(), error: vi.fn() }) }))
vi.mock("@/services/agentCoreService", () => ({
  generateSessionId: () => "s".repeat(36),
  setAgentConfig: vi.fn(),
  stopRuntimeSession: vi.fn(),
  invokeAgentCore,
  resumeLocalAgent: vi.fn(async () => ({ working: false, completion: "" })),
}))
vi.mock("@/services/deckService", () => ({
  createReview,
  getChatHistory,
  patchDeck: vi.fn(),
  batchGetSlidePreviewUrls: vi.fn(async () => new Map()),
  fetchStyles: vi.fn(async () => []),
  fetchTemplates: vi.fn(async () => []),
}))
vi.mock("@/services/kiroSessionsService", () => ({ forkKiroSession: vi.fn(), listKiroSessions: vi.fn(async () => ({ recent: [] })) }))

import { ChatPanel } from "./ChatPanel"
import { ReviewProvider, useReview, type ReviewContextValue } from "@/components/review/ReviewProvider"

const fixture = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../tests/fixtures/review_submissions.json"), "utf-8"),
) as { message_case: { id: string; expected_message: string } }
const ID = fixture.message_case.id
const MESSAGE = fixture.message_case.expected_message

let api: ReviewContextValue
const setApi = (value: ReviewContextValue | null) => { api = value as ReviewContextValue }
function Capture() {
  setApi(useReview())
  return null
}

const fetchMock = vi.fn<(...args: unknown[]) => Promise<Response>>(async () => new Response("{}", { headers: { "content-type": "application/json" } }))

async function renderPanel() {
  const view = renderWithIntl(
    <ReviewProvider deckId="d1" slugs={["intro", "sales"]} enabled agentBusy={false} openChat={() => {}} idToken="tok">
      <Capture />
      <ChatPanel deckId="d1" />
    </ReviewProvider>,
  )
  await waitFor(() => expect(getChatHistory).toHaveBeenCalled())
  return view
}

/** Draw and save a comment, as the canvas and card do. */
function addSaved(slide: string, text: string) {
  act(() => { api.addFrame(slide, [10, 20, 300, 200]) })
  act(() => { api.setEditorText(text) })
  act(() => { api.closeEditor(true) })
}

/** Type the note and press 修正を依頼. */
async function requestChanges(note: string) {
  const textarea = screen.getByRole("textbox") as HTMLTextAreaElement
  fireEvent.change(textarea, { target: { value: note } })
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Request changes" })) })
}

function deferred() {
  let resolve!: () => void
  let reject!: (err: Error) => void
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const sendButton = () => screen.getByRole("button", { name: "Request changes" }) as HTMLButtonElement
const textbox = () => screen.getByRole("textbox") as HTMLTextAreaElement

describe("ChatPanel change request", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.stubGlobal("fetch", fetchMock)
    Element.prototype.scrollIntoView = vi.fn()
    getChatHistory.mockResolvedValue({ messages: [], truncated: false })
    createReview.mockResolvedValue({ id: ID, message: MESSAGE })
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("takes the sent frames off at once and shows the card without a status", async () => {
    const turn = deferred()
    invokeAgentCore.mockImplementation(() => turn.promise)
    const { container } = await renderPanel()
    addSaved("intro", "bigger")
    await requestChanges("overall")

    expect(createReview).toHaveBeenCalledWith("d1", expect.objectContaining({ note: "overall" }), "tok")
    expect(invokeAgentCore.mock.calls[0][0]).toBe(MESSAGE)
    expect(api.drafts).toEqual([])
    await waitFor(() => expect(container.querySelector("[data-review-request-card]")).not.toBeNull())
    expect(container.querySelector("[data-review-status]")).toBeNull()

    await act(async () => { turn.resolve() })
    expect(api.drafts).toEqual([])
    expect(container.querySelector("[data-review-status]")).toBeNull()
  })

  it("puts the frames and the note back when the turn fails", async () => {
    invokeAgentCore.mockRejectedValue(new Error("network down"))
    const { container } = await renderPanel()
    addSaved("intro", "bigger")
    addSaved("sales", "")
    await requestChanges("overall")

    await waitFor(() => expect(api.drafts.map(d => d.text)).toEqual(["bigger", ""]))
    expect(api.readyDrafts).toHaveLength(2)
    expect(container.querySelector("[data-review-status]")).toBeNull()
    await waitFor(() => expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("overall"))
  })

  it("sends frames without a comment once the note is set", async () => {
    invokeAgentCore.mockResolvedValue(undefined)
    await renderPanel()
    addSaved("intro", "")
    expect(sendButton().disabled).toBe(true)
    await requestChanges("make @A the title")
    expect(createReview).toHaveBeenCalledWith("d1", {
      note: "make @A the title",
      comments: [{ name: "A", slide: "intro", rect: [10, 20, 300, 200], text: "" }],
    }, "tok")
  })

  it("keeps the message placeholder while frames exist", async () => {
    await renderPanel()
    const placeholder = textbox().placeholder
    addSaved("intro", "bigger")
    expect(textbox().placeholder).toBe(placeholder)
    expect(textbox().placeholder).not.toMatch(/note/i)
  })

  it("says what is missing until a comment or a message is written", async () => {
    const { container } = await renderPanel()
    const hint = () => container.querySelector("[data-review-needs-text]")
    addSaved("intro", "")
    expect(hint()?.textContent).toBe("Add a comment or a message to send")
    expect(sendButton().disabled).toBe(true)

    fireEvent.change(textbox(), { target: { value: " \u3000\n" } })
    expect(hint()).not.toBeNull()
    fireEvent.change(textbox(), { target: { value: "make @A the title" } })
    expect(hint()).toBeNull()
    expect(sendButton().disabled).toBe(false)

    fireEvent.change(textbox(), { target: { value: "" } })
    expect(hint()).not.toBeNull()
    addSaved("sales", "bigger")
    expect(hint()).toBeNull()
    expect(sendButton().disabled).toBe(false)
  })
})
