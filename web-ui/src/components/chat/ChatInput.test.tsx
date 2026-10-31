// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { createRef } from "react"
import { act, cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { PickerItem } from "@/lib/slashToken"
import { ChatInput, type ChatInputHandle, type ChatInputProps } from "./ChatInput"

vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))
vi.mock("@/services/deckService", () => ({
  fetchTemplates: vi.fn(),
  fetchStyles: vi.fn(),
}))

const slashItems: PickerItem[] = [
  {
    kind: "template",
    name: "corporate",
    description: "Structured business template",
    source: "builtin",
    pinned: false,
  },
  {
    kind: "style",
    name: "lumina",
    description: "Editorial style",
    source: "builtin",
    pinned: false,
  },
]

function renderInput(overrides: Partial<ChatInputProps> = {}) {
  const onSend = vi.fn()
  const handle = createRef<ChatInputHandle>()
  renderWithIntl(
    <ChatInput
      ref={handle}
      onSend={onSend}
      isLoading={false}
      onStop={vi.fn()}
      slashItems={slashItems}
      {...overrides}
    />,
  )
  return {
    onSend,
    handle,
    textarea: screen.getByRole("textbox", { name: "Chat message input" }) as HTMLTextAreaElement,
  }
}

function changeValue(textarea: HTMLTextAreaElement, value: string) {
  fireEvent.change(textarea, { target: { value, selectionStart: value.length } })
}

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.clearAllMocks()
})

describe("ChatInput slash picker", () => {
  it("opens on slash and inserts the keyboard-selected style without sending", () => {
    const { onSend, textarea } = renderInput()

    changeValue(textarea, "/")
    expect(screen.getByRole("listbox", { name: "Template, style and format suggestions" })).toBeTruthy()
    expect(textarea.getAttribute("aria-expanded")).toBe("true")

    fireEvent.keyDown(textarea, { key: "ArrowDown" })
    fireEvent.keyDown(textarea, { key: "Enter" })

    expect(textarea.value).toBe("@style:lumina ")
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(textarea.closest("form")?.hasAttribute("data-landed")).toBe(true)
  })

  it("closes on Escape and does not reopen for the same slash fragment", () => {
    const { textarea } = renderInput()

    changeValue(textarea, "/")
    expect(screen.getByRole("listbox")).toBeTruthy()

    fireEvent.keyDown(textarea, { key: "Escape" })
    expect(screen.queryByRole("listbox")).toBeNull()

    changeValue(textarea, "/s")
    expect(screen.queryByRole("listbox")).toBeNull()

    changeValue(textarea, "/s /")
    expect(screen.getByRole("listbox")).toBeTruthy()
  })

  it("does not send with Enter while the picker is open when sendWithEnter is enabled", () => {
    localStorage.setItem("sdpm-prefs", JSON.stringify({ sendWithEnter: true }))
    const { onSend, textarea } = renderInput({ slashItems: [slashItems[1]] })

    changeValue(textarea, "/")
    fireEvent.keyDown(textarea, { key: "Enter" })

    expect(textarea.value).toBe("@style:lumina ")
    expect(onSend).not.toHaveBeenCalled()
  })

  it("is inert when slashItems is omitted", () => {
    localStorage.setItem("sdpm-prefs", JSON.stringify({ sendWithEnter: true }))
    const { onSend, textarea } = renderInput({ slashItems: undefined })

    changeValue(textarea, "/")
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(textarea.hasAttribute("aria-expanded")).toBe(false)

    fireEvent.keyDown(textarea, { key: "Enter" })
    expect(onSend).toHaveBeenCalledTimes(1)
    expect(onSend.mock.calls[0][0]).toBe("/")
  })

  it("opens when a slash is inserted programmatically (empty-state hint)", () => {
    const { handle, textarea } = renderInput()
    textarea.focus()
    textarea.setSelectionRange(0, 0)

    act(() => { handle.current?.insertAtCursor("/") })

    expect(screen.getByRole("listbox")).toBeTruthy()
    expect(textarea.getAttribute("aria-expanded")).toBe("true")
  })
})

describe("ChatInput replaceText", () => {
  it("replaces the whole input, notifies onInputChange and keeps focus with the caret at the end", () => {
    const onInputChange = vi.fn()
    const { handle, textarea } = renderInput({ onInputChange })
    changeValue(textarea, "a launch deck")
    onInputChange.mockClear()

    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(0); return 0 })
    act(() => handle.current?.replaceText("@format:html a launch deck"))
    raf.mockRestore()

    expect(textarea.value).toBe("@format:html a launch deck")
    expect(onInputChange).toHaveBeenCalledWith("@format:html a launch deck")
    expect(document.activeElement).toBe(textarea)
    expect(textarea.selectionStart).toBe("@format:html a launch deck".length)
  })

  it("mirrors picker inserts and the send reset through onInputChange", () => {
    const onInputChange = vi.fn()
    const { onSend, textarea } = renderInput({ onInputChange })
    changeValue(textarea, "/")
    fireEvent.keyDown(textarea, { key: "ArrowDown" })
    fireEvent.keyDown(textarea, { key: "Enter" })
    expect(onInputChange).toHaveBeenLastCalledWith("@style:lumina ")

    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true })
    expect(onSend).toHaveBeenCalled()
    expect(onInputChange).toHaveBeenLastCalledWith("")
  })
})

describe("ChatInput send override and keep-on-failure", () => {
  it("renders the override label and sends with an empty input", () => {
    const { onSend } = renderInput({ sendOverride: { label: "Request changes", blocked: false } })
    const button = screen.getByRole("button", { name: "Request changes" }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
    fireEvent.click(button)
    expect(onSend).toHaveBeenCalledWith("", [], [], [])
  })

  it("disables the override button while blocked", () => {
    const { onSend, textarea } = renderInput({ sendOverride: { label: "Request changes", blocked: true } })
    const button = screen.getByRole("button", { name: "Request changes" }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    changeValue(textarea, "fix it")
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true })
    expect(onSend).not.toHaveBeenCalled()
  })

  it("keeps the text when onSend resolves to false", async () => {
    const onSend = vi.fn(async () => false as const)
    const { textarea } = renderInput({ onSend, sendOverride: { label: "Request changes", blocked: false } })
    changeValue(textarea, "make it shorter")
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Request changes" }))
    })
    expect(onSend).toHaveBeenCalledWith("make it shorter", [], [], [])
    expect(textarea.value).toBe("make it shorter")
  })

  it("clears the text when an async onSend succeeds", async () => {
    const onSend = vi.fn(async () => undefined)
    const { textarea } = renderInput({ onSend })
    changeValue(textarea, "hello")
    await act(async () => {
      fireEvent.keyDown(textarea, { key: "Enter", metaKey: true })
    })
    expect(onSend).toHaveBeenCalled()
    expect(textarea.value).toBe("")
  })

  it("renders the top slot inside the form", () => {
    const { textarea } = renderInput({ topSlot: <div data-testid="top-slot" /> })
    expect(textarea.closest("form")?.querySelector("[data-testid='top-slot']")).toBeTruthy()
  })
})
