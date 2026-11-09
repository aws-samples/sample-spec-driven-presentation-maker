// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatPanel naming: a chat on an existing style tells the agent which style it edits
 * (`[Style: <name>]` on the first message); a new style's chat sends no name, so the agent
 * names the style itself, and the save it reports reaches the parent.
 */

import { forwardRef } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { ToolUseCallbackData } from "@/hooks/useChatStream"

const { sendMessage, streamOptions } = vi.hoisted(() => ({
  sendMessage: vi.fn(async () => true),
  streamOptions: { current: null as null | { onToolEvent?: (name: string, data: ToolUseCallbackData | undefined) => void } },
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
    return { messages: [], isLoading: false, stopping: false, reconnecting: false, sendMessage, stopGeneration: vi.fn() }
  },
}))
vi.mock("./ChatInput", () => ({
  ChatInput: forwardRef(function ChatInput({ onSend }: { onSend: (text: string, files: [], snippets: [], attachments: []) => void }, _ref) {
    return <button onClick={() => onSend("make it calm", [], [], [])}>send</button>
  }),
}))

import { StyleChatPanel } from "./StyleChatPanel"

const firstSent = () => (sendMessage.mock.calls[0] as unknown[])[0] as string

describe("StyleChatPanel naming", () => {
  beforeEach(() => { vi.clearAllMocks() })
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
