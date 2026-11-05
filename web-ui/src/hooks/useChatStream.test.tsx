// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A Local 409 session conflict is shown as its own translated message instead of the
 * generic "Sorry, something went wrong". A send while the invoke runs is a steer into it,
 * shown where the turn's stream reports it accepted; Stop marks an unread one not delivered.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { NextIntlClientProvider } from "next-intl"
import type { ReactNode } from "react"
import en from "../../messages/en.json"

const { invokeAgentCore, stopLocalAgent, steerLocalAgent, notifyError } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(), stopLocalAgent: vi.fn(), steerLocalAgent: vi.fn(), notifyError: vi.fn(),
}))
vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/services/agentCoreService", () => ({ invokeAgentCore, stopRuntimeSession: vi.fn() }))
vi.mock("@/services/localService", () => ({ stopLocalAgent, steerLocalAgent }))
vi.mock("@/lib/errors", () => ({ notifyError }))

import { useChatStream, type Message } from "./useChatStream"

beforeEach(() => {
  vi.clearAllMocks()
})

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

describe("useChatStream stopGeneration (local)", () => {
  it("asks the local agent to stop the session", async () => {
    stopLocalAgent.mockResolvedValueOnce(undefined)
    const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
    act(() => result.current.stopGeneration())
    expect(stopLocalAgent).toHaveBeenCalledWith({ sessionId: "K1" })
  })

  it("reports a failed stop with the translated message", async () => {
    const error = new Error("HTTP 500")
    stopLocalAgent.mockRejectedValueOnce(error)
    const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
    await act(async () => { result.current.stopGeneration() })
    expect(notifyError).toHaveBeenCalledWith(en.chat.errorStopGeneration, error)
  })
})

type Handlers = {
  onStreamUpdate: (text: string) => void
  onSession: { onEvent: (ev: Record<string, unknown>, info: { own: boolean }) => void }
}

/** Capture the handlers of the invoke the hook starts; `finish` ends its stream. */
function captureInvoke() {
  const run: { handlers?: Handlers; finish?: () => void } = {}
  invokeAgentCore.mockImplementationOnce((...args: unknown[]) => new Promise<string>((resolve) => {
    run.handlers = { onStreamUpdate: args[2] as Handlers["onStreamUpdate"], onSession: args[11] as Handlers["onSession"] }
    run.finish = () => resolve("")
  }))
  return run
}

const roles = (messages: Message[]) => messages.map((m) => `${m.role}:${m.content}`)

describe("useChatStream steer (local)", () => {
  it("sends a message while the invoke runs into its session and shows it where the stream accepted it", async () => {
    const run = captureInvoke()
    const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
    let first: Promise<boolean> | undefined
    act(() => { first = result.current.sendMessage("count", undefined, undefined, undefined, { sessionIdOverride: "C9" }) })
    act(() => { run.handlers!.onStreamUpdate("one two") })

    steerLocalAgent.mockResolvedValueOnce(undefined)
    let ok: boolean | undefined
    await act(async () => { ok = await result.current.sendMessage("stop counting") })
    expect(ok).toBe(true)
    expect(invokeAgentCore).toHaveBeenCalledTimes(1)
    expect(steerLocalAgent).toHaveBeenCalledWith("C9", expect.any(String), "stop counting")
    const id = steerLocalAgent.mock.calls[0][1] as string

    act(() => {
      run.handlers!.onSession.onEvent({ steer: { id, text: "stop counting", state: "accepted" } }, { own: true })
      run.handlers!.onStreamUpdate("one two three")
    })
    expect(roles(result.current.messages)).toEqual(["user:count", "assistant:one two", "user:stop counting", "assistant: three"])
    expect(result.current.messages[2]).toMatchObject({ steerId: id, steerState: "accepted" })

    act(() => { run.handlers!.onSession.onEvent({ steer: { id, state: "delivered" } }, { own: true }) })
    expect(result.current.messages[2].steerState).toBe("delivered")
    await act(async () => { run.finish!(); await first })
    expect(result.current.isLoading).toBe(false)
  })

  it("keeps the input and tells the user when kiro-cli does not take the message", async () => {
    const run = captureInvoke()
    const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
    act(() => { void result.current.sendMessage("count") })
    steerLocalAgent.mockRejectedValueOnce(Object.assign(new Error("Steer failed: 409"), { code: "session_idle" }))
    let ok: boolean | undefined
    await act(async () => { ok = await result.current.sendMessage("more") })
    expect(ok).toBe(false)
    expect(notifyError).toHaveBeenCalledWith(en.chat.steerFailed, expect.any(Error))
    expect(roles(result.current.messages)).toEqual(["user:count", "assistant:"])
    await act(async () => { run.finish!() })
  })

  it("marks a message the agent had not read not delivered on Stop", async () => {
    const run = captureInvoke()
    const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
    act(() => { void result.current.sendMessage("count") })
    steerLocalAgent.mockResolvedValue(undefined)
    await act(async () => { await result.current.sendMessage("read me") })
    await act(async () => { await result.current.sendMessage("and me") })
    const [read, unread] = steerLocalAgent.mock.calls.map((c) => c[1] as string)
    act(() => {
      run.handlers!.onSession.onEvent({ steer: { id: read, text: "read me", state: "accepted" } }, { own: true })
      run.handlers!.onSession.onEvent({ steer: { id: read, state: "delivered" } }, { own: true })
      run.handlers!.onSession.onEvent({ steer: { id: unread, text: "and me", state: "accepted" } }, { own: true })
    })
    stopLocalAgent.mockResolvedValueOnce(undefined)
    act(() => result.current.stopGeneration())
    expect(result.current.messages.find((m) => m.steerId === read)?.steerNotDelivered).toBeUndefined()
    expect(result.current.messages.find((m) => m.steerId === unread)?.steerNotDelivered).toBe(true)
    await act(async () => { run.finish!() })
  })
})
