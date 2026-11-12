// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatPanel naming: a chat on an existing style tells the agent which style it edits
 * (`[Style: <name>]` on the first message); a new style's chat sends no name, so the agent
 * names the style itself, and the save it reports reaches the parent.
 *
 * StyleChatPanel send: a message clears the input when it is sent (ChatInput waits only for a
 * Promise, and sendMessage settles at the end of the turn), a steer too; a steer that could
 * not be sent puts its text back into the input.
 */

import { forwardRef, useImperativeHandle } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { SendMessageOptions, ToolUseCallbackData } from "@/hooks/useChatStream"

const { sendMessage, streamOptions, streamState, onSendResult, replaceText } = vi.hoisted(() => ({
  replaceText: vi.fn(),
  sendMessage: vi.fn(async (..._args: unknown[]) => true),
  streamOptions: { current: null as null | { onToolEvent?: (name: string, data: ToolUseCallbackData | undefined) => void } },
  streamState: { isLoading: false },
  /** What the panel's onSend returned: ChatInput clears the input at once unless it is a Promise. */
  onSendResult: { current: undefined as unknown },
}))

vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { id_token: "tok", access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/services/agentCoreService", () => ({ generateSessionId: () => "s".repeat(36), setAgentConfig: vi.fn() }))
vi.mock("@/services/localService", () => ({ saveLocalChat: vi.fn(async () => {}) }))
vi.mock("@/hooks/useChatStream", () => ({
  useChatStream: (options: typeof streamOptions.current) => {
    streamOptions.current = options
    return {
      messages: [], isLoading: streamState.isLoading, stopping: false, reconnecting: false, sendMessage, stopGeneration: vi.fn(),
      steerQueue: [], dismissSteer: vi.fn(), arrivedSteerIds: new Set(),
    }
  },
}))
vi.mock("./ChatInput", () => ({
  ChatInput: forwardRef(function ChatInput({ onSend }: { onSend: (text: string, files: [], snippets: [], attachments: []) => unknown }, ref) {
    useImperativeHandle(ref, () => ({ replaceText, textareaRef: { current: { value: "" } } }))
    return <button onClick={() => { onSendResult.current = onSend("make it calm", [], [], []) }}>send</button>
  }),
}))

import { StyleChatPanel } from "./StyleChatPanel"

const firstSent = () => (sendMessage.mock.calls[0] as unknown[])[0] as string

describe("StyleChatPanel naming", () => {
  beforeEach(() => { vi.clearAllMocks(); streamState.isLoading = false })
  afterEach(() => { cleanup() })

  it("names the open style on the first message", async () => {
    renderWithIntl(<StyleChatPanel styleId="brand-blue" />)
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "send" })) })
    expect(firstSent()).toBe("[Style: brand-blue]\n\nmake it calm")
  })

  it("sends a new style's first message without a name and reports the agent's save", async () => {
    const onStyleSaved = vi.fn()
    renderWithIntl(<StyleChatPanel styleId="" onStyleSaved={onStyleSaved} />)
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "send" })) })
    expect(firstSent()).toBe("make it calm")

    const saved = { title: "calm-review — For quiet reviews", filename: "calm-review.html" }
    act(() => { streamOptions.current?.onToolEvent?.("run_style_python", { completed: true, result: { saved } } as ToolUseCallbackData) })
    expect(onStyleSaved).toHaveBeenCalledWith(saved)
  })
})

describe("StyleChatPanel send", () => {
  beforeEach(() => { vi.clearAllMocks(); streamState.isLoading = false; onSendResult.current = undefined })
  afterEach(() => { cleanup() })

  it("lets the input clear as soon as a message is sent, before the agent's turn ends", async () => {
    sendMessage.mockImplementationOnce(() => new Promise<boolean>(() => {}))
    renderWithIntl(<StyleChatPanel styleId="brand-blue" />)
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "send" })) })
    expect(sendMessage).toHaveBeenCalledTimes(1)
    expect(onSendResult.current).not.toBeInstanceOf(Promise)
  })

  it("clears the input at once for a steer and puts its text back when it was not sent", async () => {
    streamState.isLoading = true
    sendMessage.mockImplementationOnce(async (...args: unknown[]) => {
      (args[4] as SendMessageOptions).onSteerFailed?.()
      return false
    })
    renderWithIntl(<StyleChatPanel styleId="brand-blue" />)
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "send" })) })
    expect(onSendResult.current).toBeUndefined()
    expect(sendMessage.mock.calls[0][4]).toMatchObject({ inputText: "make it calm" })
    await waitFor(() => expect(replaceText).toHaveBeenCalledWith("make it calm"))
  })

  it("leaves the input empty when a steer is sent", async () => {
    streamState.isLoading = true
    renderWithIntl(<StyleChatPanel styleId="brand-blue" />)
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "send" })) })
    expect(onSendResult.current).toBeUndefined()
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
    expect(replaceText).not.toHaveBeenCalled()
  })
})
