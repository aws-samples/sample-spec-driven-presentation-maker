// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { OutlineChatContext, type OutlineChatBridge } from "./OutlineChatContext"
import { OutlineView } from "./OutlineView"

const putOutline = vi.hoisted(() => vi.fn<() => Promise<void>>())
vi.mock("@/services/deckService", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/services/deckService")>()
  return { ...original, putOutline }
})
vi.mock("@dnd-kit/react", () => ({
  DragDropProvider: ({ children }: { children: React.ReactNode }) => children,
  DragOverlay: ({ children }: { children: React.ReactNode }) => children,
  useDroppable: () => ({ ref: () => {}, isDropTarget: false }),
}))
vi.mock("@dnd-kit/react/sortable", () => ({
  useSortable: () => ({ ref: () => {}, isDragging: false, isDropTarget: false }),
}))

const BASE = [
  "# Product strategy",
  "",
  "## Opening",
  "",
  "- [welcome] Welcome to the presentation",
  "  - body: The full opening message",
  "  - visual: Hero image",
  "  - evidence: Customer study",
  "",
  "- [agenda] Today’s agenda",
  "",
].join("\n")

function renderOutline(content = BASE, bridge?: Partial<OutlineChatBridge>) {
  const value: OutlineChatBridge = {
    isLoading: false,
    sendMessage: vi.fn<(text: string, options?: { displayContent?: string }) => Promise<void>>(async () => {}),
    ...bridge,
  }
  const view = (nextContent = content, nextBridge = value) => (
    <OutlineChatContext.Provider value={nextBridge}>
      <OutlineView content={nextContent} deckId="deck-1" idToken="token" />
    </OutlineChatContext.Provider>
  )
  const result = renderWithIntl(view())
  return { ...result, bridge: value, rerenderOutline: (nextContent: string, nextBridge = value) => result.rerender(view(nextContent, nextBridge)) }
}

beforeEach(() => {
  localStorage.clear()
  putOutline.mockReset()
  putOutline.mockResolvedValue()
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe("OutlineView editing", () => {
  it("edits a field and shows the exact dirty line count", () => {
    renderOutline()
    const title = screen.getByRole("textbox", { name: "Slide 1 claim" })
    fireEvent.focus(title)
    fireEvent.change(title, { target: { value: "A sharper opening claim" } })
    fireEvent.blur(title)

    expect(screen.getByText("2 unsent changed lines")).toBeTruthy()
    expect(screen.getByRole("button", { name: /Send changes/ })).toBeTruthy()
  })

  it("writes the outline before sending the localized chat message with all conditions", async () => {
    const sendMessage = vi.fn<(text: string, options?: { displayContent?: string }) => Promise<void>>(async () => {})
    const { rerenderOutline } = renderOutline(BASE, { sendMessage })
    const title = screen.getByRole("textbox", { name: "Slide 1 claim" })
    fireEvent.focus(title)
    fireEvent.change(title, { target: { value: "My edited claim" } })
    fireEvent.blur(title)

    const latest = BASE.replace("Today’s agenda", "Agent changed the agenda")
    rerenderOutline(latest, { isLoading: false, sendMessage })
    fireEvent.click(screen.getByRole("button", { name: "Add slide" }))
    fireEvent.click(screen.getByRole("button", { name: /Send changes/ }))

    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce())
    expect(putOutline).toHaveBeenCalledWith("deck-1", expect.stringContaining("- [slide-3]"), "token")
    expect(putOutline.mock.invocationCallOrder[0]).toBeLessThan(sendMessage.mock.invocationCallOrder[0])
    const [body, options] = sendMessage.mock.calls[0]
    expect(body).toContain("I manually edited outline.md.\n\n```diff")
    expect(body).toContain("The new slide slugs (`slide-3`) are placeholders")
    expect(body).toContain("Keep the intent, but polish any rough wording.")
    expect(body).toContain("You also updated outline.md before I sent this")
    expect(options?.displayContent).toMatch(/^📝 Edited and sent outline \(\+\d+ lines \/ −\d+ lines\)$/)
  })

  it("does not send a chat message when persistence fails", async () => {
    const sendMessage = vi.fn<(text: string, options?: { displayContent?: string }) => Promise<void>>(async () => {})
    putOutline.mockRejectedValueOnce(new Error("disk full"))
    renderOutline(BASE, { sendMessage })
    fireEvent.change(screen.getByRole("textbox", { name: "Slide 1 claim" }), { target: { value: "Changed" } })
    fireEvent.click(screen.getByRole("button", { name: /Send changes/ }))
    await waitFor(() => expect(putOutline).toHaveBeenCalledOnce())
    expect(sendMessage).not.toHaveBeenCalled()
  })

  it("disables sending and explains why while the agent streams", () => {
    renderOutline(BASE, { isLoading: true })
    fireEvent.change(screen.getByRole("textbox", { name: "Slide 1 claim" }), { target: { value: "Changed" } })
    const send = screen.getByRole("button", { name: /Send changes/ }) as HTMLButtonElement
    expect(send.disabled).toBe(true)
    expect(send.title).toBe("Wait until the agent finishes before sending changes")
    expect(screen.getByText("The agent is working. outline may still be updated.")).toBeTruthy()
  })

  it("takes live updates while clean, freezes while dirty, and discards to the latest", async () => {
    const { rerenderOutline } = renderOutline()
    const cleanUpdate = BASE.replace("Welcome to the presentation", "Agent clean claim")
    rerenderOutline(cleanUpdate)
    expect((screen.getByRole("textbox", { name: "Slide 1 claim" }) as HTMLTextAreaElement).value).toBe("Agent clean claim")

    fireEvent.change(screen.getByRole("textbox", { name: "Slide 1 claim" }), { target: { value: "My local claim" } })
    const laterUpdate = cleanUpdate.replace("Today’s agenda", "Agent later agenda")
    rerenderOutline(laterUpdate)
    expect((screen.getByRole("textbox", { name: "Slide 1 claim" }) as HTMLTextAreaElement).value).toBe("My local claim")
    expect(screen.getByDisplayValue("Today’s agenda")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "Discard" }))
    expect(screen.getByDisplayValue("Agent clean claim")).toBeTruthy()
    expect(screen.getByDisplayValue("Agent later agenda")).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole("button", { name: /Send changes/ })).toBeNull())
  })

  it("adds, duplicates, deletes, and nudges cards while keeping slugs read-only", async () => {
    const { container } = renderOutline()
    fireEvent.click(screen.getByRole("button", { name: "Add slide" }))
    await waitFor(() => expect(container.querySelector("[data-slide-slug='slide-3']")).toBeTruthy())
    expect(screen.queryByRole("textbox", { name: /slug/i })).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Duplicate slide 1" }))
    expect(container.querySelector("[data-slide-slug='welcome-copy']")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Delete slide 2" }))
    await waitFor(() => expect(container.querySelector("[data-slide-slug='welcome-copy']")).toBeNull())

    const welcome = container.querySelector<HTMLElement>("[data-slide-slug='welcome']")!
    fireEvent.keyDown(welcome, { key: "ArrowDown", altKey: true })
    const order = [...container.querySelectorAll<HTMLElement>("[data-slide-slug]")].map((node) => node.dataset.slideSlug)
    expect(order).toEqual(["agenda", "welcome", "slide-3"])
  })

  it("switches and persists the animated storyboard layout", async () => {
    const first = renderOutline()
    fireEvent.click(screen.getByRole("button", { name: "Column" }))
    expect(first.container.querySelector(".storyboard-view")?.className).toContain("storyboard-layout-column")
    expect(localStorage.getItem("sdpm-outline-layout")).toBe("column")
    first.unmount()
    const second = renderOutline()
    await waitFor(() => expect(second.container.querySelector(".storyboard-view")?.className).toContain("storyboard-layout-column"))
  })

  it("offers a first-chapter action for a truly empty outline", () => {
    renderOutline("")
    expect(screen.getByRole("heading", { name: "No outline yet" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Create the first chapter" }))
    expect(screen.getByRole("textbox", { name: "Chapter 1 title" })).toBeTruthy()
  })
})
