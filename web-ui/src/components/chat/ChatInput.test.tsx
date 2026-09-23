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
    expect(screen.getByRole("listbox", { name: "Template and style suggestions" })).toBeTruthy()
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
