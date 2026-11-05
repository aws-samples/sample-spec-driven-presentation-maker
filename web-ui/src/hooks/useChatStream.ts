// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useChatStream — Core streaming state management for agent chat.
 *
 * Extracted from ChatPanel.tsx to enable reuse across deck and style chat panels.
 * Manages: messages, isLoading, invokeAgentCore, abort, tool state, blocks rebuild.
 *
 * Cloud: `isLoading` is "the session is working" (a turn runs, or one it started follows).
 * A message sent while it works is a steer (steerAgentCore): its bubble appears where the
 * agent accepted it, and the reply after it goes into a new assistant message. Stop sends a
 * cancel (cancelAgentCore). `resume` follows a session that was working when the page
 * loaded; a send while it connects waits for its answer. Local keeps one request at a time and its own stop.
 *
 * Cloud background compose: `taskStart` gives the compose card a running task, which stays
 * running across later turns and messages until `taskEnd` closes it. `turnActive` is "a
 * turn runs" (Local: `isLoading`), so the panel can tell turns from the background wait.
 * A composer's report (`composerNote`) becomes a note message of its own.
 *
 * Does NOT manage: chat history loading, Local reconnect, @mentions, Options, saveLocalChat.
 * Those remain in each panel's orchestrator.
 */

"use client"

import { useState, useRef, useCallback } from "react"
import { useTranslations } from "next-intl"
import { useAuth } from "@/hooks/useAuth"
import { IS_LOCAL } from "@/lib/mode"
import { cancelAgentCore, invokeAgentCore, resumeAgentCore, steerAgentCore, stopRuntimeSession } from "@/services/agentCoreService"
import { stopLocalAgent } from "@/services/localService"
import type { ToolUse } from "@/components/chat/ChatMessage"
import type { McpServerStatus } from "@/components/chat/McpStatusBar"
import type { UploadedFile } from "@/services/uploadService"
import { userMessageFromText } from "@/components/chat/chatHistory"
import { notifyError } from "@/lib/errors"
import { agentErrorMessage, classifyAgentError } from "@/lib/agentErrors"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"
import { isSessionConflictCode } from "@/lib/local/sessionErrors"
import { isLocalTurnErrorCode, LOCAL_TURN_ERROR_KEYS } from "@/lib/local/turnErrors"

export interface SendMessageOptions {
  displayContent?: string
  continuedFrom?: SessionOrigin
  sessionIdOverride?: string
  hideUserMessage?: boolean
  propagateError?: boolean
}

export interface Message {
  role: "user" | "assistant"
  content: string
  toolUses: ToolUse[]
  blocks?: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[]
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
  mcpStatus?: McpServerStatus[]
  /** Cloud: the id of the steer this user message is. */
  steerId?: string
  /** Cloud: the steer was dropped by a stop before it reached the agent. */
  steerNotDelivered?: boolean
  /** Cloud: the steer is waiting for the agent (accepted) or the agent has read it (delivered). */
  steerState?: "accepted" | "delivered"
  /** Cloud: a composer's report to the orchestrator (`report_to_orchestrator`). */
  composerNote?: ComposerNote
}

export interface ComposerNote {
  /** 1-based group of the compose_slides call. */
  group: number
  slugs?: string
  text: string
}

/** Shape of tool-use callback data from the agent streaming API. */
export interface ToolUseCallbackData {
  toolUseId?: string
  completed?: boolean
  status?: "success" | "error"
  result?: Record<string, unknown>
  input?: Record<string, unknown>
  stream?: boolean
  data?: Record<string, unknown>
  /** Cloud: the tool now runs in the background (`taskStart`). */
  taskStarted?: boolean
  /** Cloud: the background task of the tool (`taskStart` / `taskEnd`). */
  task?: ToolUse["task"]
}

export interface UseChatStreamOptions {
  sessionId: string
  mode: string
  deckId?: string
  /** Called on every tool event (start, complete, stream). Panel handles side effects. */
  onToolEvent?: (toolName: string, data: ToolUseCallbackData | undefined) => void
  /** Called after each send completes (success or abort). */
  onSendComplete?: () => void
}

export interface UseChatStreamReturn {
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  isLoading: boolean
  /** Resolves false when the message was not sent or the turn failed (a stop is not a failure). */
  sendMessage: (text: string, uploadedFiles?: UploadedFile[], snippets?: { label: string; text: string }[], sentAttachments?: { fileName: string; fileType: string }[], options?: SendMessageOptions) => Promise<boolean>
  stopGeneration: () => void
  /**
   * Cloud: follow the session if it is working (after a reload). `cutHistory(prompt)` returns
   * the messages before the prompt that opened the work, which the replay then rebuilds.
   */
  resume: (cutHistory: (prompt: string) => Message[]) => Promise<void>
  /** Cloud: the connection dropped while the session works and is being restored. */
  reconnecting: boolean
  /** Cloud: a stop was sent and the session has not stopped yet. */
  stopping: boolean
  /** A turn runs (Cloud: between `turn` and `turnEnd`; Local: `isLoading`). */
  turnActive: boolean
  /** Ref to current messages for external reads without re-render dependency. */
  messagesRef: React.MutableRefObject<Message[]>
  /** The stream parser's translator for error codes (Local reconnect parses its own stream). */
  translateError: (code: string) => string | undefined
}

type Block = { type: "text"; text: string } | { type: "tool"; tool: ToolUse }

/**
 * Rebuild blocks array from cumulative text + tool positions.
 */
function rebuildBlocks(
  text: string,
  toolMap: Map<string, ToolUse>,
  toolOrder: string[],
  toolPositions: Map<string, number>,
): Block[] {
  const result: Block[] = []
  let textStart = 0
  for (const id of toolOrder) {
    const pos = toolPositions.get(id) ?? textStart
    const tool = toolMap.get(id)
    if (!tool) continue
    const slice = text.slice(textStart, pos)
    if (slice) result.push({ type: "text", text: slice })
    result.push({ type: "tool", tool })
    textStart = pos
  }
  const trailing = text.slice(textStart)
  if (trailing) result.push({ type: "text", text: trailing })
  return result
}

/** One assistant message of a run: where its text starts in the run's text, and its tools. */
interface Segment {
  start: number
  toolOrder: string[]
  /** Tool positions in the segment's own text. */
  positions: Map<string, number>
}

interface PendingSteer {
  display: string
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
}

interface SessionEventInfo { own: boolean }
type SessionEvent = {
  work?: { state?: string }
  turn?: { id?: string; why?: string; text?: string }
  turnEnd?: { id?: string }
  steer?: { id?: string; text?: string; state?: string }
  composerNote?: { toolUseId?: string; group?: number; slugs?: string; text?: string }
}

const emptyAssistant = (): Message => ({ role: "assistant", content: "", toolUses: [] })

/** An assistant placeholder nothing has been written into yet. */
const isBlankAssistant = (m: Message | undefined) =>
  m?.role === "assistant" && !m.content && m.toolUses.length === 0 && !m.composerNote

function blocksFor(content: string, toolUses: ToolUse[], segment: Segment): Block[] {
  return rebuildBlocks(content, new Map(toolUses.map((t) => [t.toolUseId, t])), segment.toolOrder, segment.positions)
}

function indexOfTool(messages: Message[], toolUseId: string | undefined): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant" && messages[i].toolUses.some((t) => t.toolUseId === toolUseId)) return i
  }
  return -1
}

/**
 * The handlers of one run: an invoke (its assistant placeholder already shown) or a resume
 * (`replayCut` set: the first prompt of the replay replaces the history after it).
 */
function createRun({ setMessages, onToolEvent, steers, segmentOpen, replayCut, setTurnActive }: {
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  onToolEvent?: (toolName: string, data: ToolUseCallbackData | undefined) => void
  steers: Map<string, PendingSteer>
  segmentOpen: boolean
  replayCut?: (prompt: string) => Message[]
  setTurnActive?: (active: boolean) => void
}) {
  let streamed = ""
  let segment: Segment = { start: 0, toolOrder: [], positions: new Map() }
  let open = segmentOpen
  let cutPending = !!replayCut
  const toolSegment = new Map<string, Segment>()
  const rendered = new Set<string>()

  const newSegment = () => {
    segment = { start: streamed.length, toolOrder: [], positions: new Map() }
    open = true
    cutPending = false
  }

  /** Output with no message of its own yet (a replay that starts mid-work): open one. */
  const ensureSegment = () => {
    if (open) return
    newSegment()
    setMessages((prev) => [...prev, emptyAssistant()])
  }

  /** A user message the agent accepted (or a composer note), followed by a new assistant message. */
  const pushUser = (user: Message, base?: Message[]) => {
    newSegment()
    setMessages((prev) => {
      let list = base ?? prev
      const last = list[list.length - 1]
      let mcpStatus: McpServerStatus[] | undefined
      if (!base && isBlankAssistant(last)) {
        mcpStatus = last.mcpStatus
        list = list.slice(0, -1)
      }
      return [...list, user, { ...emptyAssistant(), ...(mcpStatus ? { mcpStatus } : {}) }]
    })
  }

  const userFor = (id: string, text: string, steer: boolean): Message => {
    const pending = steers.get(id)
    const user = pending
      ? {
          role: "user" as const, content: pending.display, toolUses: [],
          ...(pending.snippets?.length ? { snippets: pending.snippets } : {}),
          ...(pending.attachments?.length ? { attachments: pending.attachments } : {}),
        }
      : userMessageFromText(text)
    return steer || pending ? { ...user, steerId: id } : user
  }

  const onStreamUpdate = (text: string) => {
    ensureSegment()
    streamed = text
    const s = segment
    const content = text.slice(s.start)
    setMessages((prev) => {
      const updated = [...prev]
      const last = updated[updated.length - 1]
      if (!last || last.role !== "assistant") return prev
      updated[updated.length - 1] = { ...last, content, blocks: blocksFor(content, last.toolUses, s) }
      return updated
    })
  }

  const onToolUse = (toolName: string, toolUseData: ToolUseCallbackData | undefined) => {
    // MCP status event
    if (toolName === "__mcp_status__" && toolUseData && "mcpStatus" in toolUseData) {
      ensureSegment()
      const incoming = (toolUseData as unknown as { mcpStatus: McpServerStatus[] }).mcpStatus
      setMessages((prev) => {
        const lastStatus = [...prev].reverse().find((m) => m.mcpStatus)?.mcpStatus
        if (lastStatus && JSON.stringify(lastStatus) === JSON.stringify(incoming)) return prev
        const updated = [...prev]
        const last = updated[updated.length - 1]
        updated[updated.length - 1] = { ...last, mcpStatus: incoming }
        return updated
      })
      return
    }

    // Tool stream event
    if (toolUseData?.stream && toolUseData?.toolUseId) {
      const d = toolUseData.data || {}
      const s = toolSegment.get(toolUseData.toolUseId) ?? segment
      setMessages((prev) => {
        const at = indexOfTool(prev, toolUseData.toolUseId)
        if (at < 0) return prev
        const updated = [...prev]
        const msg = updated[at]
        const idx = msg.toolUses.findIndex((t: ToolUse) => t.toolUseId === toolUseData.toolUseId)
        const newToolUses = [...msg.toolUses]
        const existing = newToolUses[idx].streamMessages || []

        let next: typeof existing
        if (d.toolResult) {
          next = existing.map((e: Record<string, unknown>) =>
            typeof e === "object" && e.toolUseId === d.toolResult
              ? { ...e, status: d.toolStatus || "success" }
              : e
          )
        } else if (d.tool) {
          const existingIdx = existing.findIndex((e: Record<string, unknown>) => typeof e === "object" && e.toolUseId === d.toolUseId)
          if (existingIdx >= 0 && d.input) {
            next = existing.map((e: Record<string, unknown>, i: number) => i === existingIdx ? { ...e, input: d.input } : e)
          } else if (existingIdx < 0) {
            next = [...existing, { tool: d.tool, group: d.group, slugs: d.slugs, toolUseId: d.toolUseId, input: d.input }]
          } else {
            return prev
          }
        } else if (d.status) {
          next = [...existing, { status: d.status, group: d.group, slugs: d.slugs, total_groups: d.total_groups, done: d.done, total: d.total, summary: d.summary, message: d.message, attempt: d.attempt, error: d.error }]
        } else {
          return prev
        }

        newToolUses[idx] = { ...newToolUses[idx], streamMessages: next }
        updated[at] = { ...msg, toolUses: newToolUses, blocks: blocksFor(msg.content, newToolUses, s) }
        return updated
      })
      onToolEvent?.(toolName, toolUseData)
      return
    }

    // Tool dispatched to the background — it keeps running (in whichever message holds it)
    if (toolUseData?.taskStarted) {
      const s = toolSegment.get(toolUseData.toolUseId ?? "") ?? segment
      setMessages((prev) => {
        const at = indexOfTool(prev, toolUseData.toolUseId)
        if (at < 0) return prev
        const updated = [...prev]
        const msg = updated[at]
        const newToolUses = msg.toolUses.map((t: ToolUse) =>
          t.toolUseId === toolUseData.toolUseId ? { ...t, task: toolUseData.task } : t)
        updated[at] = { ...msg, toolUses: newToolUses, blocks: blocksFor(msg.content, newToolUses, s) }
        return updated
      })
      onToolEvent?.(toolName, toolUseData)
      return
    }

    // Tool completed — update status/result (in whichever message holds the tool)
    if (toolUseData?.completed) {
      const s = toolSegment.get(toolUseData.toolUseId ?? "") ?? segment
      setMessages((prev) => {
        const at = indexOfTool(prev, toolUseData.toolUseId)
        if (at < 0) return prev
        const updated = [...prev]
        const msg = updated[at]
        const newToolUses = msg.toolUses.map((t: ToolUse) =>
          t.toolUseId === toolUseData.toolUseId
            ? { ...t, status: toolUseData.status, result: toolUseData.result, ...(toolUseData.task ? { task: toolUseData.task } : {}) }
            : t)
        updated[at] = { ...msg, toolUses: newToolUses, blocks: blocksFor(msg.content, newToolUses, s) }
        return updated
      })
      onToolEvent?.(toolName, toolUseData)
      return
    }

    // Tool started — add to toolUses
    const toolUse: ToolUse = {
      toolUseId: toolUseData?.toolUseId || crypto.randomUUID(),
      name: toolName,
      input: toolUseData?.input || {},
    }
    const known = toolSegment.has(toolUse.toolUseId)
    if (!known) {
      ensureSegment()
      segment.positions.set(toolUse.toolUseId, streamed.length - segment.start)
      segment.toolOrder.push(toolUse.toolUseId)
      toolSegment.set(toolUse.toolUseId, segment)
    }
    const s = toolSegment.get(toolUse.toolUseId) as Segment
    const content = streamed.slice(s.start)

    setMessages((prev) => {
      const found = known ? indexOfTool(prev, toolUse.toolUseId) : -1
      const at = found >= 0 ? found : prev.length - 1
      const msg = prev[at]
      if (!msg || msg.role !== "assistant") return prev
      const updated = [...prev]
      const existingIdx = msg.toolUses.findIndex((t: ToolUse) => t.toolUseId === toolUse.toolUseId)
      const newToolUses = existingIdx >= 0
        ? msg.toolUses.map((t: ToolUse, i: number) => i === existingIdx ? { ...t, ...toolUse, status: t.status, result: t.result } : t)
        : [...msg.toolUses, toolUse]
      const text = s === segment ? content : msg.content
      updated[at] = { ...msg, content: text, blocks: blocksFor(text, newToolUses, s), toolUses: newToolUses }
      return updated
    })
    onToolEvent?.(toolName, toolUseData)
  }

  const onSession = {
    onEvent(ev: SessionEvent, { own }: SessionEventInfo) {
      // A resume run shows every user message: this page's own ones went up in a run before it
      // (the deck opened again in this tab) or are steers kept in `steers`.
      const mine = own && !replayCut
      if (ev.turn) setTurnActive?.(true)
      else if (ev.turnEnd || ev.work?.state === "idle") setTurnActive?.(false)
      const note = ev.composerNote
      if (note) {
        const key = `${note.toolUseId ?? ""}:${note.group ?? ""}:${note.text ?? ""}`
        if (rendered.has(key)) return
        rendered.add(key)
        pushUser({
          ...emptyAssistant(),
          composerNote: { group: note.group ?? 0, ...(note.slugs ? { slugs: note.slugs } : {}), text: note.text ?? "" },
        })
        return
      }
      const turn = ev.turn
      if (turn?.id && turn.why === "prompt") {
        if (rendered.has(turn.id)) return
        rendered.add(turn.id)
        // This page's own prompt: its bubble went up when it was sent.
        if (mine && !steers.has(turn.id)) return
        const user = userFor(turn.id, turn.text ?? "", false)
        if (cutPending && replayCut) {
          pushUser(user, replayCut(turn.text ?? ""))
        } else {
          pushUser(user)
        }
        return
      }
      const steer = ev.steer
      if (!steer?.id) return
      if (steer.state === "accepted") {
        if (rendered.has(steer.id)) return
        rendered.add(steer.id)
        if (mine && !steers.has(steer.id)) return
        pushUser({ ...userFor(steer.id, steer.text ?? "", true), steerState: "accepted" })
      } else if (steer.state === "delivered") {
        const id = steer.id
        setMessages((prev) => prev.map((m) => (m.steerId === id ? { ...m, steerState: "delivered" } : m)))
      } else if (steer.state === "discarded") {
        const id = steer.id
        setMessages((prev) => prev.map((m) => (m.steerId === id ? { ...m, steerNotDelivered: true } : m)))
      }
    },
  }

  return { onStreamUpdate, onToolUse, onSession }
}

export function useChatStream({ sessionId, mode, deckId, onToolEvent, onSendComplete }: UseChatStreamOptions): UseChatStreamReturn {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [stopping, setStopping] = useState(false)
  // Cloud: a turn runs (`turn` … `turnEnd`); false while only background work goes on.
  const [cloudTurnActive, setCloudTurnActive] = useState(false)
  // Synchronous re-entry guard: setIsLoading(true) below is React state
  // and does not flip until the next render, so two near-simultaneous
  // triggers (Enter key repeat, double click, fast tap) both pass the
  // isLoading check above and end up firing /api/agent/invoke twice in
  // parallel, producing duplicate user bubbles and parallel streams.
  // Updated synchronously at function entry and reset in finally.
  // Cloud: also "the session is working", which turns a send into a steer.
  const isLoadingRef = useRef(false)
  // Cloud: a resume is waiting for its answer (working or not).
  const resumingRef = useRef(false)
  // Cloud: settles when a send can be routed after a resume — at its ack when the session
  // works (a steer), or when the resume is over (a prompt). Null when no resume runs.
  const resumeGateRef = useRef<Promise<void> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const steersRef = useRef(new Map<string, PendingSteer>())
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const auth = useAuth()
  const t = useTranslations("chat")

  const translateError = useCallback(
    (code: string) => code === "session_reload_required"
      ? t("errorSessionReloadRequired")
      : isLocalTurnErrorCode(code) ? t(LOCAL_TURN_ERROR_KEYS[code]) : undefined,
    [t],
  )

  const stopGeneration = useCallback(() => {
    if (IS_LOCAL) {
      abortControllerRef.current?.abort()
      stopLocalAgent({ sessionId }).catch((err) => notifyError(t("errorStopGeneration"), err))
      return
    }
    const token = auth.user?.access_token
    if (!token) return
    setStopping(true)
    cancelAgentCore(sessionId, token)
      .catch((err: unknown) => {
        console.error("Stop failed", err)
        void stopRuntimeSession(sessionId, token)
      })
      .finally(() => setStopping(false))
  }, [sessionId, auth.user?.access_token, t])

  const sendMessage = useCallback(async (
    userMessage: string,
    uploadedFiles?: UploadedFile[],
    snippets?: { label: string; text: string }[],
    sentAttachments?: { fileName: string; fileType: string }[],
    options?: SendMessageOptions,
  ) => {
    const hasContent = userMessage.trim() || uploadedFiles?.length || snippets?.length
    if (!hasContent && !options?.continuedFrom) return false
    const display = options?.displayContent ?? userMessage

    // Cloud, resume connecting (reload, wake, deck opened again): wait until the session's
    // state is known, then send as a steer or a prompt.
    if (!IS_LOCAL && resumeGateRef.current) await resumeGateRef.current

    // Cloud, session working: a steer into the running work.
    if (!IS_LOCAL && isLoadingRef.current) {
      const accessToken = auth.user?.access_token
      if (!accessToken || !hasContent) return false
      const id = crypto.randomUUID()
      steersRef.current.set(id, { display, snippets, attachments: sentAttachments })
      try {
        await steerAgentCore(sessionId, userMessage, accessToken, id)
        return true
      } catch (err) {
        steersRef.current.delete(id)
        notifyError(t("steerFailed"), err)
        return false
      }
    }
    if (IS_LOCAL && isLoading) return false
    if (isLoadingRef.current || resumingRef.current) return false
    isLoadingRef.current = true

    const accessToken = auth.user?.access_token
    const userId = auth.user?.profile?.sub
    if (!IS_LOCAL && (!accessToken || !userId)) {
      isLoadingRef.current = false
      return false
    }
    let ok = true

    setMessages((prev) => [
      ...prev,
      ...(!options?.hideUserMessage
        ? [{ role: "user" as const, content: display, toolUses: [], snippets: snippets && snippets.length > 0 ? snippets : undefined, attachments: sentAttachments && sentAttachments.length > 0 ? sentAttachments : undefined }]
        : []),
      emptyAssistant(),
    ])
    setIsLoading(true)
    setCloudTurnActive(true)

    const controller = new AbortController()
    abortControllerRef.current = controller
    const run = createRun({ setMessages, onToolEvent, steers: steersRef.current, segmentOpen: true, setTurnActive: setCloudTurnActive })

    try {
      await invokeAgentCore(
        userMessage,
        options?.sessionIdOverride ?? sessionId,
        run.onStreamUpdate,
        accessToken,
        userId,
        run.onToolUse,
        controller.signal,
        mode,
        deckId,
        options?.continuedFrom,
        translateError,
        { onEvent: run.onSession.onEvent, onReconnecting: setReconnecting },
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // Keep partial response
      } else {
        if (options?.propagateError) {
          setMessages([])
          throw err
        }
        ok = false
        const errorMessage = err instanceof Error ? err.message : String(err)
        const code = classifyAgentError(errorMessage)
        const conflictCode = (err as { code?: unknown }).code
        // A Local turn that ended without an answer keeps what was already streamed.
        const turnError = isLocalTurnErrorCode(conflictCode) ? t(LOCAL_TURN_ERROR_KEYS[conflictCode]) : null
        // Transport-level failures don't carry raw model errors worth showing —
        // always use the friendly classified message here.
        const displayMessage = isSessionConflictCode(conflictCode)
          ? t(conflictCode === "session_busy" ? "sessionBusy" : "sessionLocked")
          : code === "internal"
            ? "Sorry, something went wrong. Please try again."
            : agentErrorMessage(errorMessage, code)
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          updated[updated.length - 1] = turnError
            ? {
                ...last,
                content: last.content ? `${last.content}\n\n⚠ ${turnError}` : `⚠ ${turnError}`,
                ...(last.blocks?.length ? { blocks: [...last.blocks, { type: "text" as const, text: `⚠ ${turnError}` }] } : {}),
              }
            : { ...last, content: displayMessage }
          return updated
        })
      }
    } finally {
      abortControllerRef.current = null
      isLoadingRef.current = false
      setIsLoading(false)
      setCloudTurnActive(false)
      setReconnecting(false)
      onSendComplete?.()
    }
    return ok
  }, [sessionId, mode, deckId, isLoading, auth.user?.access_token, auth.user?.profile?.sub, onToolEvent, onSendComplete, t, translateError])

  const resume = useCallback(async (cutHistory: (prompt: string) => Message[]) => {
    if (IS_LOCAL || isLoadingRef.current || resumingRef.current) return
    const accessToken = auth.user?.access_token
    if (!accessToken) return
    resumingRef.current = true
    let openGate = () => {}
    const gate = new Promise<void>((resolve) => { openGate = resolve })
    resumeGateRef.current = gate
    const run = createRun({ setMessages, onToolEvent, steers: steersRef.current, segmentOpen: false, replayCut: cutHistory, setTurnActive: setCloudTurnActive })
    let followed = false
    try {
      await resumeAgentCore(sessionId, accessToken, 0, {
        onResumeAck: (ack: { working?: boolean }) => {
          resumingRef.current = false
          if (ack.working) {
            followed = true
            isLoadingRef.current = true
            setIsLoading(true)
            openGate()
          }
        },
        onStreamUpdate: run.onStreamUpdate,
        onToolUse: run.onToolUse,
        onSession: { onEvent: run.onSession.onEvent, onReconnecting: setReconnecting },
        translateError,
      })
    } catch (err) {
      // A newer invoke or resume on the session took over (AbortError): nothing failed.
      if (!(err instanceof DOMException && err.name === "AbortError")) console.error("Resume failed:", err)
    } finally {
      resumingRef.current = false
      setReconnecting(false)
      if (followed) {
        isLoadingRef.current = false
        setIsLoading(false)
        setCloudTurnActive(false)
        onSendComplete?.()
      }
      if (resumeGateRef.current === gate) resumeGateRef.current = null
      openGate()
    }
  }, [sessionId, auth.user?.access_token, onToolEvent, onSendComplete, translateError])

  const turnActive = IS_LOCAL ? isLoading : cloudTurnActive
  return { messages, setMessages, isLoading, sendMessage, stopGeneration, resume, reconnecting, stopping, turnActive, messagesRef, translateError }
}
