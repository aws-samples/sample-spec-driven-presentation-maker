// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useChatStream — Core streaming state management for agent chat.
 *
 * Extracted from ChatPanel.tsx to enable reuse across deck and style chat panels.
 * Manages: messages, isLoading, invokeAgentCore, abort, tool state, blocks rebuild.
 *
 * Cloud: `isLoading` is "the session is working" (a turn runs, or one it started follows).
 * A message sent while it works is a steer (steerAgentCore). Stop sends a cancel
 * (cancelAgentCore). `resume` follows a session that was working when the page loaded; a
 * send while it connects waits for its answer.
 *
 * Local: one invoke at a time; its stream lasts the chat's work period (every turn of it). A
 * message sent while it runs is a steer too (steerLocalAgent): the stream reports it with the
 * same `steer` events (a steer the prompt ended without reading continues the turn, as in
 * Cloud). Stop ends the invoke at once; a steer the agent had not read by then is not
 * delivered (the server clears it from kiro-cli's queue). `resume` follows a period that runs
 * (or ended unseen) when the deck is reloaded or reopened (resumeLocalAgent); a send while it
 * connects waits for its answer, and a send while it follows is a steer into that period.
 *
 * Steers (both modes): a steer waits in `steerQueue` (the cards above the input), `sending`
 * until the request is answered or the stream reports it `accepted`, then `waiting`. One sent
 * from another tab joins the queue at its `accepted`. When the agent reads it (`delivered`) it
 * leaves the queue and becomes a user message there, the reply after it going into a new
 * assistant message, and its id is in `arrivedSteerIds` for a moment. A steer the work dropped
 * (`discarded`, a Local Stop, or work that ended without reading it) stays in the queue as
 * `notDelivered` until `dismissSteer`. A failed request leaves the queue at once and calls the
 * send's `onSteerFailed`.
 *
 * Background compose: `taskStart` gives the compose card a running task, which stays running
 * across later turns and messages until `taskEnd` closes it. `turnActive` is "a turn runs"
 * (between `turn` and `turnEnd`), so the panel can tell turns from the background wait.
 * A composer's report (`composerNote`) becomes a note message of its own.
 *
 * Does NOT manage: chat history loading, @mentions, Options, saveLocalChat.
 * Those remain in each panel's orchestrator.
 */

"use client"

import { useState, useRef, useCallback, useEffect } from "react"
import { useTranslations } from "next-intl"
import { useAuth } from "@/hooks/useAuth"
import { IS_LOCAL } from "@/lib/mode"
import { cancelAgentCore, invokeAgentCore, resumeAgentCore, resumeLocalAgent, steerAgentCore, stopRuntimeSession } from "@/services/agentCoreService"
import { steerLocalAgent, stopLocalAgent } from "@/services/localService"
import type { ToolUse } from "@/components/chat/ChatMessage"
import type { McpServerStatus } from "@/components/chat/McpStatusBar"
import type { UploadedFile } from "@/services/uploadService"
import { typedText, userMessageFromText } from "@/components/chat/chatHistory"
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
  /** A steer: the text the user typed, which "back to input" puts into the input (default: the shown text). */
  inputText?: string
  /** A steer that was not sent (the request failed): called after it left the queue. */
  onSteerFailed?: () => void
}

/** A steer the agent has not read yet (a card above the input). */
export interface QueuedSteer {
  id: string
  /** `sending`: the request is out; `waiting`: accepted, the agent has not read it; `notDelivered`: dropped. */
  state: "sending" | "waiting" | "notDelivered"
  /** The text its user message shows. */
  display: string
  /** The text the user typed. */
  inputText: string
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
}

export interface Message {
  role: "user" | "assistant"
  content: string
  toolUses: ToolUse[]
  blocks?: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[]
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
  mcpStatus?: McpServerStatus[]
  /** The id of the steer this user message is (shown where the agent read it). */
  steerId?: string
  /** Cloud: a composer's report to the orchestrator (`report_to_orchestrator`). */
  composerNote?: ComposerNote
  /** Local: a notice about the session this reply ran in (lib/local/sessionNotices.ts code). */
  localNotice?: string
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
  /**
   * Called after each send completes (success or abort), and after a resume that followed work.
   * Local: with the session id whose stream the run read, which the panel's next save reports
   * delivered (the server stops replaying that period once the chat holding it is saved).
   */
  onSendComplete?: (streamed?: string) => void
  /** Called when a turn ends (`turnEnd`), while the work may go on. */
  onTurnEnd?: () => void
}

export interface UseChatStreamReturn {
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  isLoading: boolean
  /** Resolves false when the message was not sent or the turn failed (a stop is not a failure). */
  sendMessage: (text: string, uploadedFiles?: UploadedFile[], snippets?: { label: string; text: string }[], sentAttachments?: { fileName: string; fileType: string }[], options?: SendMessageOptions) => Promise<boolean>
  stopGeneration: () => void
  /**
   * Follow the session if it is working (after a reload or on a reopened deck; Local: also a
   * period that ended before a page saved it). `cutHistory(prompt)` returns the messages
   * before the prompt that opened the work, which the replay then rebuilds (Local's replay always
   * starts with that prompt: chat.ts never drops a period's opening events). Local resolves
   * `true` when it followed a period, `false` when the server said nothing runs, and `undefined`
   * when it did not run, the request failed, or a newer resume or Stop ended it; Cloud resolves
   * `undefined`.
   */
  resume: (cutHistory: (prompt: string) => Message[]) => Promise<boolean | undefined>
  /** Cloud: the connection dropped while the session works and is being restored. */
  reconnecting: boolean
  /** Cloud: a stop was sent and the session has not stopped yet. */
  stopping: boolean
  /** A turn runs (between `turn` and `turnEnd`); false while only background work goes on. */
  turnActive: boolean
  /** Ref to current messages for external reads without re-render dependency. */
  messagesRef: React.MutableRefObject<Message[]>
  /** The stream parser's translator for error codes. */
  translateError: (code: string) => string | undefined
  /** The steers the agent has not read yet, in sent order. */
  steerQueue: QueuedSteer[]
  /** Remove a steer from the queue (a not-delivered card closed or put back into the input). */
  dismissSteer: (id: string) => void
  /** Steers that became user messages a moment ago (their bubble is highlighted briefly). */
  arrivedSteerIds: ReadonlySet<string>
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
  inputText: string
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
  /** The stream reported it accepted (a request that then fails was still sent). */
  accepted?: boolean
}

/** What a run does with the steer queue. */
interface SteerQueueOps {
  /** Accepted: into the queue (another tab's), or on from `sending`. */
  waiting: (id: string, steer: PendingSteer) => void
  notDelivered: (id: string) => void
  /** The agent read it (or it became a turn of its own): out of the queue. */
  remove: (id: string) => void
  /** Its user message went up just now. */
  arrived: (id: string) => void
}

interface SessionEventInfo { own: boolean }
type SessionEvent = {
  work?: { state?: string }
  turn?: { id?: string; why?: string; text?: string }
  turnEnd?: { id?: string }
  steer?: { id?: string; text?: string; state?: string }
  composerNote?: { toolUseId?: string; group?: number; slugs?: string; text?: string }
  /** Local: the invoke stream's `notice` code. */
  localNotice?: string
}

const emptyAssistant = (): Message => ({ role: "assistant", content: "", toolUses: [] })

/** How long a steer's bubble stays highlighted after the agent read it. */
const STEER_ARRIVED_MS = 2000

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
function createRun({ setMessages, onToolEvent, steers, queue, segmentOpen, replayCut, setTurnActive, onTurnEnd }: {
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  onToolEvent?: (toolName: string, data: ToolUseCallbackData | undefined) => void
  steers: Map<string, PendingSteer>
  queue: SteerQueueOps
  segmentOpen: boolean
  replayCut?: (prompt: string) => Message[]
  setTurnActive?: (active: boolean) => void
  onTurnEnd?: () => void
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

  /** A new assistant message with no user message before it (a hidden first prompt). */
  const openAssistant = (base?: Message[]) => {
    newSegment()
    setMessages((prev) => {
      const list = base ?? prev
      return !base && isBlankAssistant(list[list.length - 1]) ? list : [...list, emptyAssistant()]
    })
  }

  /** A user message the agent read (or a composer note), followed by a new assistant message. */
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
      // Local: a notice about the session this reply runs in (it comes before any output).
      if (IS_LOCAL && ev.localNotice) {
        const code = ev.localNotice
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role !== "assistant") return prev
          return [...prev.slice(0, -1), { ...last, localNotice: code }]
        })
        return
      }
      if (ev.turn) setTurnActive?.(true)
      else if (ev.turnEnd || ev.work?.state === "idle") setTurnActive?.(false)
      if (ev.turnEnd) onTurnEnd?.()
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
        // A steer that became a turn of its own (the work ended as it arrived): its bubble goes here.
        queue.remove(turn.id)
        // This page's own prompt: its bubble went up when it was sent.
        if (mine && !steers.has(turn.id)) return
        // A hidden first message (a fork's): the reply starts without a user bubble.
        if (!turn.text) {
          openAssistant(cutPending && replayCut ? replayCut("") : undefined)
          return
        }
        const user = userFor(turn.id, turn.text, false)
        if (cutPending && replayCut) {
          pushUser(user, replayCut(turn.text))
        } else {
          pushUser(user)
        }
        return
      }
      const steer = ev.steer
      if (!steer?.id) return
      const id = steer.id
      if (steer.state === "accepted") {
        if (rendered.has(id)) return
        rendered.add(id)
        // Another tab's steer (or this one's from before a reload): known from here on.
        if (!steers.has(id)) {
          const user = userMessageFromText(steer.text ?? "")
          steers.set(id, {
            display: user.content, inputText: typedText(steer.text ?? ""),
            ...(user.attachments ? { attachments: user.attachments } : {}),
          })
        }
        const pending = steers.get(id) as PendingSteer
        pending.accepted = true
        queue.waiting(id, pending)
      } else if (steer.state === "delivered") {
        const key = `delivered:${id}`
        // Its `accepted` was not seen: nothing to show it with.
        if (rendered.has(key) || !steers.has(id)) return
        rendered.add(key)
        queue.remove(id)
        pushUser(userFor(id, "", true))
        queue.arrived(id)
      } else if (steer.state === "discarded") {
        queue.notDelivered(id)
      }
    },
  }

  return { onStreamUpdate, onToolUse, onSession }
}

export function useChatStream({ sessionId, mode, deckId, onToolEvent, onSendComplete, onTurnEnd }: UseChatStreamOptions): UseChatStreamReturn {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [stopping, setStopping] = useState(false)
  // A turn runs (`turn` … `turnEnd`); false while only background work goes on.
  const [turnActiveState, setTurnActiveState] = useState(false)
  // Synchronous re-entry guard: setIsLoading(true) below is React state
  // and does not flip until the next render, so two near-simultaneous
  // triggers (Enter key repeat, double click, fast tap) both pass the
  // isLoading check above and end up firing /api/agent/invoke twice in
  // parallel, producing duplicate user bubbles and parallel streams.
  // Updated synchronously at function entry and reset in finally.
  // Cloud: also "the session is working", which turns a send into a steer.
  const isLoadingRef = useRef(false)
  // A resume is waiting for its answer (working or not).
  const resumingRef = useRef(false)
  // Settles when a send can be routed after a resume — at its ack when the session
  // works (a steer), or when the resume is over (a prompt). Null when no resume runs.
  const resumeGateRef = useRef<Promise<void> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  // Local: the session the running invoke (or the followed period) went to (a steer goes to the same one).
  const localRunSessionRef = useRef<string | null>(null)
  // Local: the resume in flight (its token, stream, session and result), so a newer one, Stop
  // and unmount end it, and a second one for the same session joins it.
  const resumeRunRef = useRef(0)
  const resumeControllerRef = useRef<AbortController | null>(null)
  const resumeInFlightRef = useRef<{ sessionId: string; done: Promise<boolean | undefined> } | null>(null)
  useEffect(() => () => resumeControllerRef.current?.abort(), [])
  const steersRef = useRef(new Map<string, PendingSteer>())
  const [steerQueue, setSteerQueue] = useState<QueuedSteer[]>([])
  const [arrivedSteerIds, setArrivedSteerIds] = useState<ReadonlySet<string>>(() => new Set())
  const arrivedTimersRef = useRef(new Set<ReturnType<typeof setTimeout>>())
  useEffect(() => {
    const timers = arrivedTimersRef.current
    return () => timers.forEach(clearTimeout)
  }, [])
  // Another chat: its steers are not this one's.
  useEffect(() => () => setSteerQueue([]), [sessionId])
  const steerQueueOps = useRef<SteerQueueOps>({
    waiting: (id, steer) => setSteerQueue((prev) => {
      const card = prev.find((s) => s.id === id)
      if (!card) return [...prev, { id, state: "waiting", ...steer }]
      return card.state === "sending" ? prev.map((s) => (s.id === id ? { ...s, state: "waiting" } : s)) : prev
    }),
    notDelivered: (id) => setSteerQueue((prev) => prev.some((s) => s.id === id && s.state !== "notDelivered")
      ? prev.map((s) => (s.id === id ? { ...s, state: "notDelivered" } : s))
      : prev),
    remove: (id) => setSteerQueue((prev) => (prev.some((s) => s.id === id) ? prev.filter((s) => s.id !== id) : prev)),
    arrived: (id) => {
      setArrivedSteerIds((prev) => new Set(prev).add(id))
      const timer = setTimeout(() => {
        arrivedTimersRef.current.delete(timer)
        setArrivedSteerIds((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      }, STEER_ARRIVED_MS)
      arrivedTimersRef.current.add(timer)
    },
  }).current
  const dismissSteer = useCallback((id: string) => steerQueueOps.remove(id), [steerQueueOps])
  /** The work ended (or stopped): a steer it did not read is not delivered. */
  const dropUnreadSteers = useCallback((which: "waiting" | "unread") => setSteerQueue((prev) => {
    const dropped = (s: QueuedSteer) => (which === "waiting" ? s.state === "waiting" : s.state !== "notDelivered")
    return prev.some(dropped) ? prev.map((s) => (dropped(s) ? { ...s, state: "notDelivered" } : s)) : prev
  }), [])
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const auth = useAuth()
  const t = useTranslations("chat")

  const translateError = useCallback(
    (code: string) => code === "session_reload_required"
      ? t("errorSessionReloadRequired")
      : code === "throttled"
        ? t("errorThrottled")
        : code === "content_filtered"
          ? t("errorContentFiltered")
          : isLocalTurnErrorCode(code) ? t(LOCAL_TURN_ERROR_KEYS[code]) : undefined,
    [t],
  )

  const stopGeneration = useCallback(() => {
    if (IS_LOCAL) {
      abortControllerRef.current?.abort()
      stopLocalAgent({ sessionId: localRunSessionRef.current ?? sessionId }).catch((err) => notifyError(t("errorStopGeneration"), err))
      // The stream is no longer read: a steer the agent had not read is dropped by this stop.
      dropUnreadSteers("unread")
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
  }, [sessionId, auth.user?.access_token, t, dropUnreadSteers])

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

    // Resume connecting (reload, wake, deck opened again): wait until the session's state is
    // known, then send as a steer or a prompt (a newer resume that took over: wait for it too).
    for (let gate = resumeGateRef.current, waited: Promise<void> | null = null; gate && gate !== waited; gate = resumeGateRef.current) {
      await gate
      waited = gate
    }

    // Session working: a steer into the running work (Local: into the running invoke's turn).
    if (isLoadingRef.current && (!IS_LOCAL || localRunSessionRef.current)) {
      const accessToken = auth.user?.access_token
      if (!hasContent) return false
      if (!IS_LOCAL && !accessToken) {
        options?.onSteerFailed?.()
        return false
      }
      const id = crypto.randomUUID()
      const pending: PendingSteer = {
        display, inputText: options?.inputText ?? display,
        ...(snippets?.length ? { snippets } : {}),
        ...(sentAttachments?.length ? { attachments: sentAttachments } : {}),
      }
      steersRef.current.set(id, pending)
      setSteerQueue((prev) => [...prev, { id, state: "sending", ...pending }])
      try {
        if (IS_LOCAL) await steerLocalAgent(localRunSessionRef.current as string, id, userMessage)
        else await steerAgentCore(sessionId, userMessage, accessToken, id)
        setSteerQueue((prev) => prev.some((s) => s.id === id && s.state === "sending")
          ? prev.map((s) => (s.id === id ? { ...s, state: "waiting" } : s))
          : prev)
        return true
      } catch (err) {
        // The stream already reported it accepted (its answer was lost): it was sent.
        if (pending.accepted) return true
        steersRef.current.delete(id)
        steerQueueOps.remove(id)
        notifyError(t("steerFailed"), err)
        options?.onSteerFailed?.()
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
    let aborted = false

    setMessages((prev) => [
      ...prev,
      ...(!options?.hideUserMessage
        ? [{ role: "user" as const, content: display, toolUses: [], snippets: snippets && snippets.length > 0 ? snippets : undefined, attachments: sentAttachments && sentAttachments.length > 0 ? sentAttachments : undefined }]
        : []),
      emptyAssistant(),
    ])
    setIsLoading(true)
    setTurnActiveState(true)

    const controller = new AbortController()
    abortControllerRef.current = controller
    const runSessionId = options?.sessionIdOverride ?? sessionId
    if (IS_LOCAL) localRunSessionRef.current = runSessionId
    const run = createRun({ setMessages, onToolEvent, steers: steersRef.current, queue: steerQueueOps, segmentOpen: true, setTurnActive: setTurnActiveState, onTurnEnd })

    try {
      await invokeAgentCore(
        userMessage,
        runSessionId,
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
        aborted = true
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
            : agentErrorMessage(errorMessage, code, translateError)
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          updated[updated.length - 1] = turnError
            ? {
                ...last,
                content: last.content ? `${last.content}\n\n⚠ ${turnError}` : `⚠ ${turnError}`,
                ...(last.blocks?.length ? { blocks: [...last.blocks, { type: "text" as const, text: `⚠ ${turnError}` }] } : {}),
              }
            : {
                ...last,
                content: displayMessage,
                // The blocks are what the reply renders: replace their text too, keep the tool cards.
                ...(last.blocks?.length
                  ? { blocks: [...last.blocks.filter((b) => b.type === "tool"), { type: "text" as const, text: displayMessage }] }
                  : {}),
              }
          return updated
        })
      }
    } finally {
      abortControllerRef.current = null
      localRunSessionRef.current = null
      isLoadingRef.current = false
      setIsLoading(false)
      setTurnActiveState(false)
      setReconnecting(false)
      // The work is over: a steer it accepted and never read will not be read now.
      if (!aborted) dropUnreadSteers("waiting")
      onSendComplete?.(IS_LOCAL ? runSessionId : undefined)
    }
    return ok
  }, [sessionId, mode, deckId, isLoading, auth.user?.access_token, auth.user?.profile?.sub, onToolEvent, onSendComplete, onTurnEnd, t, translateError, steerQueueOps, dropUnreadSteers])

  /** Local resume: follow the chat's work period over GET /api/agent/stream. */
  const resumeLocal = useCallback(async (cutHistory: (prompt: string) => Message[]): Promise<boolean | undefined> => {
    const previous = resumeControllerRef.current
    // A send's invoke runs: it already follows the period.
    if (isLoadingRef.current && !previous) return undefined
    // The same session again (its history loaded twice): join the one in flight. Replacing it
    // could lose a finished period whose replay the server already marked delivered.
    const inFlight = resumeInFlightRef.current
    if (previous && inFlight?.sessionId === sessionId) return inFlight.done
    if (previous) {
      // A resume for the deck's own session id (it arrived after the mount): it replaces the one in flight.
      previous.abort()
      resumeControllerRef.current = null
      if (abortControllerRef.current === previous) abortControllerRef.current = null
      isLoadingRef.current = false
      localRunSessionRef.current = null
      setIsLoading(false)
    }
    const token = ++resumeRunRef.current
    const controller = new AbortController()
    resumeControllerRef.current = controller
    resumingRef.current = true
    let openGate = () => {}
    const gate = new Promise<void>((resolve) => { openGate = resolve })
    resumeGateRef.current = gate
    const run = createRun({ setMessages, onToolEvent, steers: steersRef.current, queue: steerQueueOps, segmentOpen: false, replayCut: cutHistory, setTurnActive: setTurnActiveState, onTurnEnd })
    let followed = false
    let aborted = false
    let settleDone: (value: boolean | undefined) => void = () => {}
    resumeInFlightRef.current = { sessionId, done: new Promise((resolve) => { settleDone = resolve }) }
    let result: boolean | undefined
    try {
      const { working } = await resumeLocalAgent(sessionId, {
        onResumeAck: (ack: { working?: boolean }) => {
          if (resumeRunRef.current !== token) return
          resumingRef.current = false
          if (ack.working) {
            followed = true
            isLoadingRef.current = true
            // A send now is a steer into this period, and Stop ends it.
            localRunSessionRef.current = sessionId
            abortControllerRef.current = controller
            setIsLoading(true)
          }
          openGate()
        },
        onStreamUpdate: run.onStreamUpdate,
        onToolUse: run.onToolUse,
        onSession: { onEvent: run.onSession.onEvent },
        translateError,
      }, { signal: controller.signal })
      result = working
    } catch (err) {
      // A newer resume, Stop or unmount ended it (AbortError): nothing failed. A failed request
      // says nothing about the session's work either.
      if (err instanceof DOMException && err.name === "AbortError") aborted = true
      else console.error("Resume failed:", err)
      result = undefined
    } finally {
      if (resumeRunRef.current === token) {
        resumeControllerRef.current = null
        resumeInFlightRef.current = null
        resumingRef.current = false
        if (abortControllerRef.current === controller) abortControllerRef.current = null
        if (followed) {
          if (localRunSessionRef.current === sessionId) localRunSessionRef.current = null
          isLoadingRef.current = false
          setIsLoading(false)
          setTurnActiveState(false)
          if (!aborted) dropUnreadSteers("waiting")
          onSendComplete?.(sessionId)
        }
      }
      if (resumeGateRef.current === gate) resumeGateRef.current = null
      openGate()
    }
    settleDone(result)
    return result
  }, [sessionId, onToolEvent, onSendComplete, onTurnEnd, translateError, steerQueueOps, dropUnreadSteers])

  const resume = useCallback(async (cutHistory: (prompt: string) => Message[]): Promise<boolean | undefined> => {
    if (IS_LOCAL) return resumeLocal(cutHistory)
    if (isLoadingRef.current || resumingRef.current) return
    const accessToken = auth.user?.access_token
    if (!accessToken) return
    resumingRef.current = true
    let openGate = () => {}
    const gate = new Promise<void>((resolve) => { openGate = resolve })
    resumeGateRef.current = gate
    const run = createRun({ setMessages, onToolEvent, steers: steersRef.current, queue: steerQueueOps, segmentOpen: false, replayCut: cutHistory, setTurnActive: setTurnActiveState, onTurnEnd })
    let followed = false
    let aborted = false
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
      if (err instanceof DOMException && err.name === "AbortError") aborted = true
      else console.error("Resume failed:", err)
    } finally {
      resumingRef.current = false
      setReconnecting(false)
      if (followed) {
        isLoadingRef.current = false
        setIsLoading(false)
        setTurnActiveState(false)
        if (!aborted) dropUnreadSteers("waiting")
        onSendComplete?.()
      }
      if (resumeGateRef.current === gate) resumeGateRef.current = null
      openGate()
    }
  }, [sessionId, auth.user?.access_token, onToolEvent, onSendComplete, onTurnEnd, translateError, resumeLocal, steerQueueOps, dropUnreadSteers])

  return {
    messages, setMessages, isLoading, sendMessage, stopGeneration, resume, reconnecting, stopping, turnActive: turnActiveState,
    messagesRef, translateError, steerQueue, dismissSteer, arrivedSteerIds,
  }
}
