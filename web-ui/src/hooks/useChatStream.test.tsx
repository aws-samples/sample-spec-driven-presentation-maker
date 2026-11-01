// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A Local 409 session conflict is shown as its own translated message instead of the
 * generic "Sorry, something went wrong".
 */

import { describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { NextIntlClientProvider } from "next-intl"
import type { ReactNode } from "react"
import en from "../../messages/en.json"

const { invokeAgentCore } = vi.hoisted(() => ({ invokeAgentCore: vi.fn() }))
vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/services/agentCoreService", () => ({ invokeAgentCore, stopRuntimeSession: vi.fn() }))

import { useChatStream } from "./useChatStream"

const wrapper = ({ children }: { children: ReactNode }) => (
  <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">{children}</NextIntlClientProvider>
)

async function lastReplyAfter(error: Error) {
  invokeAgentCore.mockRejectedValueOnce(error)
  const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
  let ok: boolean | undefined
  await act(async () => { ok = await result.current.sendMessage("hi") })
  expect(ok).toBe(false)
  return result.current.messages.at(-1)?.content
}

describe("useChatStream session conflicts", () => {
  it.each([
    ["session_busy", en.chat.sessionBusy],
    ["session_locked", en.chat.sessionLocked],
  ])("shows the %s message", async (code, expected) => {
    const error = Object.assign(new Error(`Local agent error: 409: {"code":"${code}"}`), { code })
    expect(await lastReplyAfter(error)).toBe(expected)
  })

  it("keeps the generic message for other failures", async () => {
    expect(await lastReplyAfter(new Error("Local agent error: 500: "))).toBe("Sorry, something went wrong. Please try again.")
  })
})
