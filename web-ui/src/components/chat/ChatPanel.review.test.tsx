// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel sending a change request (Local mode): the frames stay on the canvas as 対応中
 * while the agent turn runs and leave when it ends; a turn that fails puts the comments back
 * into the drafts and the note back into the input, and saves the message flagged `failed`,
 * so its card shows 未完了 live and after a reload.
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

const fetchMock = vi.fn(async (..._args: unknown[]) => new Response("{}", { headers: { "content-type": "application/json" } }))

/** Bodies of the Local chat saves (`POST /api/agent/chat`). */
const savedChats = () => fetchMock.mock.calls
  .filter(([url]) => url === "/api/agent/chat")
  .map(([, init]) => JSON.parse((init as RequestInit).body as string) as { messages: { role: string; failed?: boolean }[] })

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

const status = (container: HTMLElement) => container.querySelector("[data-review-status]")?.getAttribute("data-review-status")

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

  it("keeps the frames on the canvas while the turn runs and removes them when it ends", async () => {
    const turn = deferred()
    invokeAgentCore.mockImplementation(() => turn.promise)
    const { container } = await renderPanel()
    addSaved("intro", "bigger")
    await requestChanges("overall")

    expect(createReview).toHaveBeenCalledWith("d1", expect.objectContaining({ note: "overall" }), "tok")
    expect(invokeAgentCore.mock.calls[0][0]).toBe(MESSAGE)
    await waitFor(() => expect(api.workingReview?.id).toBe(ID))
    expect(api.openSent.map(f => f.name)).toEqual(["A", "C", "B"])
    expect(api.drafts).toEqual([])
    expect(status(container)).toBe("working")

    await act(async () => { turn.resolve() })
    await waitFor(() => expect(api.workingReview).toBeNull())
    expect(api.openSent).toEqual([])
    expect(status(container)).toBe("done")
  })

  it("puts the comments and the note back and shows 未完了 when the turn fails", async () => {
    invokeAgentCore.mockRejectedValue(new Error("network down"))
    const { container } = await renderPanel()
    addSaved("intro", "bigger")
    addSaved("sales", "@A colour")
    await requestChanges("overall")

    await waitFor(() => expect(api.drafts.map(d => d.text)).toEqual(["bigger", "@A colour"]))
    expect(api.readyDrafts).toHaveLength(2)
    expect(api.openSent).toEqual([])
    expect(status(container)).toBe("failed")
    expect(screen.queryByText("Done")).toBeNull()
    await waitFor(() => expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("overall"))
    // The one save at the end of the turn (.chat.json) carries the flag, so the card restores as 未完了.
    expect(savedChats()).toHaveLength(1)
    expect(savedChats()[0].messages.find(m => m.role === "user")?.failed).toBe(true)
  })
})
