// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useChatStream in Cloud mode: a send while the session works is a steer, shown where the
 * agent accepted it; stop sends a cancel; resume rebuilds a working session after a reload.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { intlWrapper } from "@/test/renderWithIntl"
import en from "../../messages/en.json"
import type { Message } from "./useChatStream"

const { invokeAgentCore, steerAgentCore, cancelAgentCore, resumeAgentCore, notifyError } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(), steerAgentCore: vi.fn(), cancelAgentCore: vi.fn(), resumeAgentCore: vi.fn(), notifyError: vi.fn(),
}))
vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: false }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/services/agentCoreService", () => ({
  invokeAgentCore, steerAgentCore, cancelAgentCore, resumeAgentCore, stopRuntimeSession: vi.fn(),
}))
vi.mock("@/services/localService", () => ({ stopLocalAgent: vi.fn() }))
vi.mock("@/lib/errors", () => ({ notifyError }))

import { useChatStream } from "./useChatStream"

type Handlers = {
  onStreamUpdate: (text: string) => void
  onToolUse: (name: string, data: Record<string, unknown>) => void
  onSession: { onEvent: (ev: Record<string, unknown>, info: { own: boolean }) => void }
}

/** Capture the handlers of the invoke the hook starts; `finish` resolves it (work idle). */
function captureInvoke() {
  const run: { handlers?: Handlers; finish?: () => void } = {}
  invokeAgentCore.mockImplementationOnce((...args: unknown[]) => new Promise<string>((resolve) => {
    run.handlers = {
      onStreamUpdate: args[2] as Handlers["onStreamUpdate"],
      onToolUse: args[5] as Handlers["onToolUse"],
      onSession: args[11] as Handlers["onSession"],
    }
    run.finish = () => resolve("")
  }))
  return run
}

const roles = (messages: Message[]) => messages.map((m) => `${m.role}:${m.content}`)

function renderStream() {
  return renderHook(() => useChatStream({ sessionId: "S1", mode: "spec", deckId: "d1" }), { wrapper: intlWrapper() })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("useChatStream (Cloud) steer", () => {
  it("sends a message while working as a steer and shows it where it was accepted", async () => {
    const run = captureInvoke()
    const { result } = renderStream()
    let first: Promise<boolean> | undefined
    act(() => { first = result.current.sendMessage("make a deck") })
    const h = run.handlers!
    act(() => {
      h.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make a deck" } }, { own: true })
      h.onStreamUpdate("Working on it.")
    })
    expect(result.current.isLoading).toBe(true)

    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "steer" })
    let ok: boolean | undefined
    await act(async () => { ok = await result.current.sendMessage("use blue", undefined, undefined, undefined, { displayContent: "use blue" }) })
    expect(ok).toBe(true)
    expect(invokeAgentCore).toHaveBeenCalledTimes(1)
    expect(steerAgentCore).toHaveBeenCalledWith("S1", "use blue", "at", expect.any(String))
    // Not shown until the agent accepted it.
    expect(roles(result.current.messages)).toEqual(["user:make a deck", "assistant:Working on it."])

    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => {
      h.onSession.onEvent({ steer: { id: steerId, text: "use blue", state: "accepted" } }, { own: true })
      h.onStreamUpdate("Working on it. Blue it is.")
    })
    expect(roles(result.current.messages)).toEqual([
      "user:make a deck", "assistant:Working on it.", "user:use blue", "assistant: Blue it is.",
    ])
    expect(result.current.messages[2].steerId).toBe(steerId)

    await act(async () => { run.finish!(); await first })
    expect(result.current.isLoading).toBe(false)
  })

  it("updates a tool card started before the steer in place when it completes after it", async () => {
    const run = captureInvoke()
    const { result } = renderStream()
    act(() => { void result.current.sendMessage("go") })
    const h = run.handlers!
    act(() => {
      h.onStreamUpdate("Composing.")
      h.onToolUse("compose_slides", { toolUseId: "t1", input: {} })
    })
    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "steer" })
    await act(async () => { await result.current.sendMessage("shorter please") })
    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => {
      h.onSession.onEvent({ steer: { id: steerId, text: "shorter please", state: "accepted" } }, { own: true })
      h.onToolUse("compose_slides", { toolUseId: "t1", completed: true, status: "success", result: { ok: true } })
      h.onStreamUpdate("Composing.Done, shorter.")
    })
    const [, card, steer, after] = result.current.messages
    expect(card.toolUses[0]).toMatchObject({ toolUseId: "t1", status: "success", result: { ok: true } })
    expect(card.blocks?.find((b) => b.type === "tool")).toMatchObject({ tool: { status: "success" } })
    expect(steer).toMatchObject({ role: "user", content: "shorter please" })
    expect(after).toMatchObject({ role: "assistant", content: "Done, shorter.", toolUses: [] })
    await act(async () => { run.finish!() })
  })

  it("keeps the input and tells the user when the steer is not accepted", async () => {
    const run = captureInvoke()
    const { result } = renderStream()
    act(() => { void result.current.sendMessage("go") })
    steerAgentCore.mockRejectedValueOnce(new Error("timeout"))
    let ok: boolean | undefined
    await act(async () => { ok = await result.current.sendMessage("more") })
    expect(ok).toBe(false)
    expect(notifyError).toHaveBeenCalledWith(en.chat.steerFailed, expect.any(Error))
    await act(async () => { run.finish!() })
  })

  it("marks a steer the stop discarded", async () => {
    const run = captureInvoke()
    const { result } = renderStream()
    act(() => { void result.current.sendMessage("go") })
    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "steer" })
    await act(async () => { await result.current.sendMessage("more") })
    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => {
      run.handlers!.onSession.onEvent({ steer: { id: steerId, text: "more", state: "accepted" } }, { own: true })
      run.handlers!.onSession.onEvent({ steer: { id: steerId, state: "discarded", how: "cancelled" } }, { own: true })
    })
    expect(result.current.messages.find((m) => m.steerId === steerId)?.steerNotDelivered).toBe(true)
    await act(async () => { run.finish!() })
  })

  it("shows a steer that became a turn at its turn", async () => {
    const run = captureInvoke()
    const { result } = renderStream()
    act(() => { void result.current.sendMessage("go") })
    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "turn" })
    await act(async () => { await result.current.sendMessage("and then") })
    const steerId = steerAgentCore.mock.calls[0][3] as string
    act(() => { run.handlers!.onSession.onEvent({ turn: { id: steerId, why: "prompt", text: "and then" } }, { own: true }) })
    expect(roles(result.current.messages)).toEqual(["user:go", "user:and then", "assistant:"])
    await act(async () => { run.finish!() })
  })
})

describe("useChatStream (Cloud) stop", () => {
  it("sends a cancel instead of stopping the runtime session", async () => {
    let release: (() => void) | undefined
    cancelAgentCore.mockImplementationOnce(() => new Promise((resolve) => { release = () => resolve("stopped") }))
    const { result } = renderStream()
    act(() => result.current.stopGeneration())
    expect(cancelAgentCore).toHaveBeenCalledWith("S1", "at")
    expect(result.current.stopping).toBe(true)
    await act(async () => { release!() })
    expect(result.current.stopping).toBe(false)
  })
})

describe("useChatStream (Cloud) resume", () => {
  it("cuts the history at the period's prompt and replays the work", async () => {
    const history: Message[] = [
      { role: "user", content: "earlier", toolUses: [] },
      { role: "assistant", content: "earlier reply", toolUses: [] },
    ]
    let finish: (() => void) | undefined
    resumeAgentCore.mockImplementationOnce((_sid: string, _tok: string, fromSeq: number, h: Record<string, (...a: unknown[]) => void> & { onSession: Handlers["onSession"] }) => {
      expect(fromSeq).toBe(0)
      h.onResumeAck({ working: true })
      h.onSession.onEvent({ work: { state: "busy" } }, { own: false })
      h.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: false })
      h.onStreamUpdate("On it")
      return new Promise((resolve) => { finish = () => resolve({ working: true, completion: "On it" }) })
    })
    const { result } = renderStream()
    const cut = vi.fn(() => history)
    let done: Promise<void> | undefined
    act(() => { done = result.current.resume(cut) })
    expect(cut).toHaveBeenCalledWith("make it")
    expect(roles(result.current.messages)).toEqual(["user:earlier", "assistant:earlier reply", "user:make it", "assistant:On it"])
    expect(result.current.isLoading).toBe(true)
    await act(async () => { finish!(); await done })
    expect(result.current.isLoading).toBe(false)
  })

  it("shows the prompt this tab sent in an earlier run when the deck opens again", async () => {
    let finish: (() => void) | undefined
    resumeAgentCore.mockImplementationOnce((_sid: string, _tok: string, _from: number, h: Record<string, (...a: unknown[]) => void> & { onSession: Handlers["onSession"] }) => {
      h.onResumeAck({ working: true })
      h.onSession.onEvent({ turn: { id: "p1", why: "prompt", text: "make it" } }, { own: true })
      h.onStreamUpdate("On it")
      return new Promise((resolve) => { finish = () => resolve({ working: true, completion: "On it" }) })
    })
    const { result } = renderStream()
    let done: Promise<void> | undefined
    act(() => { done = result.current.resume(() => []) })
    expect(roles(result.current.messages)).toEqual(["user:make it", "assistant:On it"])
    await act(async () => { finish!(); await done })
  })

  it("sends a message typed while the resume connects as a steer once the session is known to work", async () => {
    let ack: (() => void) | undefined
    resumeAgentCore.mockImplementationOnce((_sid: string, _tok: string, _from: number, h: Record<string, (...a: unknown[]) => void>) =>
      new Promise((resolve) => { ack = () => h.onResumeAck({ working: true }); void resolve }))
    steerAgentCore.mockResolvedValueOnce({ id: "x", as: "steer" })
    const { result } = renderStream()
    act(() => { void result.current.resume(() => []) })
    let sent: Promise<boolean> | undefined
    act(() => { sent = result.current.sendMessage("use blue") })
    expect(steerAgentCore).not.toHaveBeenCalled()
    expect(invokeAgentCore).not.toHaveBeenCalled()
    await act(async () => { ack!() })
    await act(async () => { await sent })
    expect(steerAgentCore).toHaveBeenCalledWith("S1", "use blue", "at", expect.any(String))
    expect(invokeAgentCore).not.toHaveBeenCalled()
  })

  it("sends a message typed while the resume connects as a prompt when the session is idle", async () => {
    let end: (() => void) | undefined
    resumeAgentCore.mockImplementationOnce((_sid: string, _tok: string, _from: number, h: Record<string, (...a: unknown[]) => void>) =>
      new Promise((resolve) => { end = () => { h.onResumeAck({ working: false }); resolve({ working: false, completion: "" }) } }))
    const run = captureInvoke()
    const { result } = renderStream()
    act(() => { void result.current.resume(() => []) })
    let sent: Promise<boolean> | undefined
    act(() => { sent = result.current.sendMessage("hello") })
    expect(invokeAgentCore).not.toHaveBeenCalled()
    await act(async () => { end!() })
    expect(invokeAgentCore).toHaveBeenCalledTimes(1)
    expect(invokeAgentCore.mock.calls[0][0]).toBe("hello")
    expect(roles(result.current.messages)).toEqual(["user:hello", "assistant:"])
    await act(async () => { run.finish!(); await sent })
    expect(steerAgentCore).not.toHaveBeenCalled()
  })
})
