// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A Local 409 session conflict is shown as its own translated message instead of the
 * generic "Sorry, something went wrong". A Local stream's session notice lands on the reply.
 * A send while the invoke runs is a steer into it, shown where the turn's stream reports it
 * accepted; Stop marks an unread one not delivered. Turn events drive `turnActive`; a resume
 * follows the chat's work period (a send during it is a steer into it, Stop ends it).
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { NextIntlClientProvider } from "next-intl"
import type { ReactNode } from "react"
import en from "../../messages/en.json"

const { invokeAgentCore, resumeLocalAgent, stopLocalAgent, steerLocalAgent, notifyError } = vi.hoisted(() => ({
  invokeAgentCore: vi.fn(), resumeLocalAgent: vi.fn(), stopLocalAgent: vi.fn(), steerLocalAgent: vi.fn(), notifyError: vi.fn(),
}))
vi.mock("@/lib/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/mode")>()), IS_LOCAL: true }))
vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { access_token: "at", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/services/agentCoreService", () => ({ invokeAgentCore, resumeLocalAgent, stopRuntimeSession: vi.fn() }))
vi.mock("@/services/localService", () => ({ stopLocalAgent, steerLocalAgent }))
vi.mock("@/lib/errors", () => ({ notifyError }))

import { cutLocalAtPrompt } from "@/components/chat/chatHistory"
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

describe("useChatStream local notice", () => {
  it("puts the stream's notice on the reply it opens", async () => {
    invokeAgentCore.mockImplementationOnce(async (...args: unknown[]) => {
      const onStreamUpdate = args[2] as (text: string) => void
      const onSession = args[11] as { onEvent: (ev: unknown, info: { own: boolean }) => void }
      onSession.onEvent({ localNotice: "context_not_carried_over" }, { own: true })
      onStreamUpdate("OK")
      return "OK"
    })
    const { result } = renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1" }), { wrapper })
    await act(async () => { await result.current.sendMessage("hi") })
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"])
    expect(result.current.messages[1]).toMatchObject({ content: "OK", localNotice: "context_not_carried_over" })
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

type ResumeHandlers = Handlers & {
  onResumeAck: (ack: { working: boolean }) => void
  onToolUse: (name: string, data: Record<string, unknown>) => void
}

/** Capture the resume the hook starts; `finish` ends its stream, its signal's abort rejects it. */
function captureResume() {
  const run: { sessionId?: string; handlers?: ResumeHandlers; signal?: AbortSignal; finish?: (working?: boolean) => void } = {}
  resumeLocalAgent.mockImplementationOnce((sessionId: string, handlers: ResumeHandlers, { signal }: { signal: AbortSignal }) =>
    new Promise((resolve, reject) => {
      Object.assign(run, { sessionId, handlers, signal })
      run.finish = (working = true) => resolve({ working, completion: "" })
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
    }))
  return run
}

const render = (options: { onSendComplete?: () => void; onTurnEnd?: () => void } = {}) =>
  renderHook(() => useChatStream({ sessionId: "K1", mode: "vibe", deckId: "d1", ...options }), { wrapper })

describe("useChatStream turns (local)", () => {
  it("drives turnActive from turn events while the period stays open, and calls onTurnEnd", async () => {
    const run = captureInvoke()
    const onTurnEnd = vi.fn()
    const { result } = render({ onTurnEnd })
    let done: Promise<boolean> | undefined
    act(() => { done = result.current.sendMessage("make it") })
    act(() => { run.handlers!.onSession.onEvent({ turn: { id: "t1", why: "prompt", text: "make it" } }, { own: true }) })
    expect(result.current.turnActive).toBe(true)
    act(() => { run.handlers!.onSession.onEvent({ turnEnd: { id: "t1", how: "finished" } }, { own: true }) })
    expect(result.current.turnActive).toBe(false)
    expect(result.current.isLoading).toBe(true)
    expect(onTurnEnd).toHaveBeenCalledTimes(1)
    act(() => { run.handlers!.onSession.onEvent({ turn: { id: "t2", why: "wake", text: "" } }, { own: true }) })
    expect(result.current.turnActive).toBe(true)
    act(() => { run.handlers!.onSession.onEvent({ work: { state: "idle", how: "finished" } }, { own: true }) })
    expect(result.current.turnActive).toBe(false)
    await act(async () => { run.finish!(); await done })
    expect(result.current.isLoading).toBe(false)
  })

  it("keeps a task card running across turnEnd and a wake turn until taskEnd", async () => {
    invokeAgentCore.mockImplementationOnce(async (...args: unknown[]) => {
      const onToolUse = args[5] as (name: string, data: Record<string, unknown>) => void
      const onSession = args[11] as Handlers["onSession"]
      onSession.onEvent({ turn: { id: "t1", why: "prompt", text: "make it" } }, { own: true })
      onToolUse("compose_slides", { toolUseId: "c1", input: {} })
      onToolUse("compose_slides", { toolUseId: "c1", taskStarted: true, task: { id: "k1", state: "running" } })
      onSession.onEvent({ turnEnd: { id: "t1", how: "finished" } }, { own: true })
      onSession.onEvent({ turn: { id: "t2", why: "wake", text: "" } }, { own: true })
      return ""
    })
    const { result } = render()
    await act(async () => { await result.current.sendMessage("make it") })
    const tool = () => result.current.messages.flatMap((m) => m.toolUses).find((t) => t.toolUseId === "c1")
    expect(tool()?.task).toEqual({ id: "k1", state: "running" })
  })
})

describe("useChatStream resume (local)", () => {
  const history: Message[] = [
    { role: "user", content: "earlier", toolUses: [] },
    { role: "assistant", content: "earlier reply", toolUses: [] },
    { role: "user", content: "make it", toolUses: [] },
    { role: "assistant", content: "stale partial", toolUses: [] },
  ]

  it("rebuilds the replayed period from its prompt, once", async () => {
    const run = captureResume()
    const { result } = render()
    act(() => { result.current.setMessages(history) })
    const cut = vi.fn((prompt: string | null) => history.slice(0, history.findLastIndex((m) => m.role === "user" && m.content === prompt)))
    let done: Promise<boolean | undefined> | undefined
    act(() => { done = result.current.resume(cut) })
    expect(run.sessionId).toBe("K1")
    act(() => {
      run.handlers!.onResumeAck({ working: true })
      run.handlers!.onSession.onEvent({ work: { state: "busy" } }, { own: false })
      run.handlers!.onSession.onEvent({ turn: { id: "t1", why: "prompt", text: "make it" } }, { own: false })
      run.handlers!.onStreamUpdate("On it")
    })
    expect(cut).toHaveBeenCalledWith("make it")
    expect(roles(result.current.messages)).toEqual(["user:earlier", "assistant:earlier reply", "user:make it", "assistant:On it"])
    expect(result.current.isLoading).toBe(true)
    await act(async () => { run.finish!(); await done })
  })

  it("rebuilds after the last user message when the replay starts after its prompt", async () => {
    const run = captureResume()
    const { result } = render()
    act(() => { result.current.setMessages(history) })
    const cut = vi.fn((prompt: string | null) => cutLocalAtPrompt(history, prompt))
    let done: Promise<boolean | undefined> | undefined
    act(() => { done = result.current.resume(cut) })
    act(() => {
      run.handlers!.onResumeAck({ working: true })
      run.handlers!.onStreamUpdate("partial and the rest")
      run.handlers!.onSession.onEvent({ steer: { id: "s1", text: "also this", state: "accepted" } }, { own: false })
      run.handlers!.onStreamUpdate("partial and the rest. More")
    })
    expect(cut).toHaveBeenCalledTimes(1)
    expect(cut).toHaveBeenCalledWith(null)
    expect(roles(result.current.messages)).toEqual(["user:earlier", "assistant:earlier reply", "user:make it", "assistant:partial and the rest", "user:also this", "assistant:. More"])
    await act(async () => { run.finish!(); await done })
  })

  it("keeps the history when the cut has nothing for a replay that starts after its prompt", async () => {
    const run = captureResume()
    const { result } = render()
    act(() => { result.current.setMessages(history) })
    let done: Promise<boolean | undefined> | undefined
    act(() => { done = result.current.resume((prompt) => (prompt === null ? undefined : [])) })
    act(() => {
      run.handlers!.onResumeAck({ working: true })
      run.handlers!.onStreamUpdate("more")
    })
    expect(roles(result.current.messages)).toEqual([...roles(history), "assistant:more"])
    await act(async () => { run.finish!(); await done })
  })

  it("resolves undefined when the stream request fails", async () => {
    resumeLocalAgent.mockImplementationOnce(async () => { throw new Error("Local stream error: 500") })
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    const { result } = render()
    let resolved: boolean | undefined = false
    await act(async () => { resolved = await result.current.resume(() => []) })
    expect(resolved).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    error.mockRestore()
  })

  it("turns a send during the followed period into a steer, and a send after it into an invoke", async () => {
    const run = captureResume()
    const onSendComplete = vi.fn()
    const { result } = render({ onSendComplete })
    let done: Promise<boolean | undefined> | undefined
    act(() => { done = result.current.resume(() => []) })
    act(() => { run.handlers!.onResumeAck({ working: true }) })
    steerLocalAgent.mockResolvedValueOnce(undefined)
    await act(async () => { await result.current.sendMessage("more") })
    expect(steerLocalAgent).toHaveBeenCalledWith("K1", expect.any(String), "more")
    expect(invokeAgentCore).not.toHaveBeenCalled()

    let resolved: boolean | undefined
    await act(async () => { run.finish!(); resolved = await done })
    expect(resolved).toBe(true)
    expect(result.current.isLoading).toBe(false)
    expect(onSendComplete).toHaveBeenCalledTimes(1)
    expect(onSendComplete).toHaveBeenCalledWith("K1")
    invokeAgentCore.mockResolvedValueOnce("")
    await act(async () => { await result.current.sendMessage("next") })
    expect(invokeAgentCore).toHaveBeenCalledTimes(1)
  })

  it("holds a send until the resume answers", async () => {
    const run = captureResume()
    const { result } = render()
    act(() => { void result.current.resume(() => []) })
    steerLocalAgent.mockResolvedValueOnce(undefined)
    let sent: Promise<boolean> | undefined
    act(() => { sent = result.current.sendMessage("waiting") })
    await act(async () => { await Promise.resolve() })
    expect(steerLocalAgent).not.toHaveBeenCalled()
    expect(invokeAgentCore).not.toHaveBeenCalled()
    await act(async () => { run.handlers!.onResumeAck({ working: true }); await sent })
    expect(steerLocalAgent).toHaveBeenCalledWith("K1", expect.any(String), "waiting")
    await act(async () => { run.finish!() })
  })

  it("ends the followed period on Stop", async () => {
    const run = captureResume()
    const { result } = render()
    let done: Promise<boolean | undefined> | undefined
    act(() => { done = result.current.resume(() => []) })
    act(() => { run.handlers!.onResumeAck({ working: true }) })
    stopLocalAgent.mockResolvedValueOnce(undefined)
    let resolved: boolean | undefined = false
    await act(async () => { result.current.stopGeneration(); resolved = await done })
    expect(run.signal!.aborted).toBe(true)
    expect(stopLocalAgent).toHaveBeenCalledWith({ sessionId: "K1" })
    expect(resolved).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
  })

  it("lets a resume for another session id replace the one in flight", async () => {
    const first = captureResume()
    const second = captureResume()
    const { result, rerender } = renderHook(({ sessionId }) => useChatStream({ sessionId, mode: "vibe", deckId: "d1" }), { wrapper, initialProps: { sessionId: "d1-padded" } })
    let firstDone: Promise<boolean | undefined> | undefined
    act(() => { firstDone = result.current.resume(() => []) })
    act(() => { first.handlers!.onResumeAck({ working: true }) })
    rerender({ sessionId: "K1" })
    let secondDone: Promise<boolean | undefined> | undefined
    act(() => { secondDone = result.current.resume(() => []) })
    expect(first.signal!.aborted).toBe(true)
    expect(second.sessionId).toBe("K1")
    let firstResult: boolean | undefined = false
    await act(async () => { firstResult = await firstDone })
    expect(firstResult).toBeUndefined()
    act(() => { second.handlers!.onResumeAck({ working: true }) })
    expect(result.current.isLoading).toBe(true)
    await act(async () => { second.finish!(); await secondDone })
    expect(result.current.isLoading).toBe(false)
  })

  it("joins the resume in flight for the same session", async () => {
    const run = captureResume()
    const { result } = render()
    let firstDone: Promise<boolean | undefined> | undefined
    let secondDone: Promise<boolean | undefined> | undefined
    act(() => { firstDone = result.current.resume(() => []) })
    act(() => { secondDone = result.current.resume(() => []) })
    expect(resumeLocalAgent).toHaveBeenCalledTimes(1)
    expect(run.signal!.aborted).toBe(false)
    act(() => { run.handlers!.onResumeAck({ working: true }) })
    let results: (boolean | undefined)[] = []
    await act(async () => { run.finish!(); results = await Promise.all([firstDone, secondDone]) })
    expect(results).toEqual([true, true])
  })

  it("resolves false when nothing runs, and undefined while a send's invoke runs", async () => {
    resumeLocalAgent.mockImplementationOnce(async (_sid: string, h: ResumeHandlers) => {
      h.onResumeAck({ working: false })
      return { working: false, completion: "" }
    })
    const { result } = render()
    let resolved: boolean | undefined = true
    await act(async () => { resolved = await result.current.resume(() => []) })
    expect(resolved).toBe(false)
    expect(result.current.isLoading).toBe(false)

    const run = captureInvoke()
    act(() => { void result.current.sendMessage("count") })
    await act(async () => { resolved = await result.current.resume(() => []) })
    expect(resolved).toBeUndefined()
    expect(resumeLocalAgent).toHaveBeenCalledTimes(1)
    await act(async () => { run.finish!() })
  })

  it("aborts the resume on unmount", async () => {
    const run = captureResume()
    const { result, unmount } = render()
    let done: Promise<boolean | undefined> | undefined
    act(() => { done = result.current.resume(() => []) })
    unmount()
    expect(run.signal!.aborted).toBe(true)
    await expect(done).resolves.toBeUndefined()
  })
})
