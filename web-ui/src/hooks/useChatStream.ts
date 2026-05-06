// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useChatStream — Core streaming state management for agent chat.
 *
 * Extracted from ChatPanel.tsx to enable reuse across deck and style chat panels.
 * Manages: messages, isLoading, invokeAgentCore, abort, tool state, blocks rebuild.
 *
 * Does NOT manage: chat history loading, reconnect, @mentions, Options, saveLocalChat.
 * Those remain in each panel's orchestrator.
 */

"use client"

import { useState, useRef, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { IS_LOCAL } from "@/lib/mode"
import { invokeAgentCore, stopRuntimeSession } from "@/services/agentCoreService"
import type { ToolUse } from "@/components/chat/ChatMessage"
import type { McpServerStatus } from "@/components/chat/McpStatusBar"
import type { UploadedFile } from "@/services/uploadService"

export interface Message {
  role: "user" | "assistant"
  content: string
  toolUses: ToolUse[]
  blocks?: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[]
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
  mcpStatus?: McpServerStatus[]
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
  sendMessage: (text: string, uploadedFiles?: UploadedFile[], snippets?: { label: string; text: string }[], sentAttachments?: { fileName: string; fileType: string }[], options?: { displayContent?: string }) => Promise<void>
  stopGeneration: () => void
  /** Ref to current messages for external reads without re-render dependency. */
  messagesRef: React.MutableRefObject<Message[]>
}

/**
 * Rebuild blocks array from cumulative text + tool positions.
 */
function rebuildBlocks(
  text: string,
  toolMap: Map<string, ToolUse>,
  toolOrder: string[],
  toolPositions: Map<string, number>,
): ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] {
  const result: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] = []
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

export function useChatStream({ sessionId, mode, deckId, onToolEvent, onSendComplete }: UseChatStreamOptions): UseChatStreamReturn {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const auth = useAuth()

  const stopGeneration = useCallback(() => {
    abortControllerRef.current?.abort()
    if (IS_LOCAL) {
      fetch("/api/agent/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId }) }).catch(() => {})
    } else {
      const token = auth.user?.access_token
      if (token) stopRuntimeSession(sessionId, token)
    }
  }, [sessionId, auth.user?.access_token])

  const sendMessage = useCallback(async (
    userMessage: string,
    uploadedFiles?: UploadedFile[],
    snippets?: { label: string; text: string }[],
    sentAttachments?: { fileName: string; fileType: string }[],
    options?: { displayContent?: string },
  ) => {
    if (!userMessage.trim() && (!uploadedFiles || uploadedFiles.length === 0) && (!snippets || snippets.length === 0)) return
    if (isLoading) return

    const accessToken = auth.user?.access_token
    const userId = auth.user?.profile?.sub
    if (!IS_LOCAL && (!accessToken || !userId)) return

    const display = options?.displayContent ?? userMessage
    setMessages((prev) => [
      ...prev,
      { role: "user", content: display, toolUses: [], snippets: snippets && snippets.length > 0 ? snippets : undefined, attachments: sentAttachments && sentAttachments.length > 0 ? sentAttachments : undefined },
      { role: "assistant", content: "", toolUses: [] },
    ])
    setIsLoading(true)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      let lastTextSnapshot = ""
      const toolPositions = new Map<string, number>()
      const toolOrder: string[] = []

      await invokeAgentCore(
        userMessage,
        sessionId,
        (streamed: string) => {
          lastTextSnapshot = streamed
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            const toolMap = new Map(last.toolUses.map((t: ToolUse) => [t.toolUseId, t]))
            const blocks = rebuildBlocks(streamed, toolMap, toolOrder, toolPositions)
            updated[updated.length - 1] = { ...last, content: streamed, blocks }
            return updated
          })
        },
        accessToken,
        userId,
        (toolName: string, toolUseData: ToolUseCallbackData | undefined) => {
          // MCP status event
          if (toolName === '__mcp_status__' && toolUseData && 'mcpStatus' in toolUseData) {
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
            setMessages((prev) => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              const idx = last.toolUses.findIndex((t: ToolUse) => t.toolUseId === toolUseData.toolUseId)
              if (idx < 0) return prev
              const newToolUses = [...last.toolUses]
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
              const toolMap = new Map(newToolUses.map((t: ToolUse) => [t.toolUseId, t]))
              const blocks = rebuildBlocks(lastTextSnapshot, toolMap, toolOrder, toolPositions)
              updated[updated.length - 1] = { ...last, toolUses: newToolUses, blocks }
              return updated
            })
            onToolEvent?.(toolName, toolUseData)
            return
          }

          // Tool completed — update status/result
          if (toolUseData?.completed) {
            setMessages((prev) => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              const idx = last.toolUses.findIndex((t: ToolUse) => t.toolUseId === toolUseData.toolUseId)
              if (idx >= 0) {
                const newToolUses = [...last.toolUses]
                newToolUses[idx] = { ...newToolUses[idx], status: toolUseData.status, result: toolUseData.result }
                const toolMap = new Map(newToolUses.map((t: ToolUse) => [t.toolUseId, t]))
                const blocks = rebuildBlocks(lastTextSnapshot, toolMap, toolOrder, toolPositions)
                updated[updated.length - 1] = { ...last, toolUses: newToolUses, blocks }
              }
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

          if (!toolPositions.has(toolUse.toolUseId)) {
            toolPositions.set(toolUse.toolUseId, lastTextSnapshot.length)
            toolOrder.push(toolUse.toolUseId)
          }

          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            const existingIdx = last.toolUses.findIndex((t: ToolUse) => t.toolUseId === toolUse.toolUseId)
            const newToolUses = existingIdx >= 0
              ? last.toolUses.map((t: ToolUse, i: number) => i === existingIdx ? { ...t, ...toolUse, status: t.status, result: t.result } : t)
              : [...last.toolUses, toolUse]
            const toolMap = new Map(newToolUses.map((t: ToolUse) => [t.toolUseId, t]))
            const blocks = rebuildBlocks(lastTextSnapshot, toolMap, toolOrder, toolPositions)
            updated[updated.length - 1] = { ...last, content: lastTextSnapshot, blocks, toolUses: newToolUses }
            return updated
          })
          onToolEvent?.(toolName, toolUseData)
        },
        controller.signal,
        mode,
        deckId,
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // Keep partial response
      } else {
        const errorMessage = err instanceof Error ? err.message : String(err)
        const isRetryable = errorMessage.includes("ThrottlingException") || errorMessage.includes("throttl")
          || errorMessage.includes("timed out") || errorMessage.includes("timeout")
          || errorMessage.includes("not ready") || errorMessage.includes("ServiceUnavailable")
        const isConversationLimit = errorMessage.includes("Too much media") || errorMessage.includes("too long")
        const displayMessage = isConversationLimit
          ? "This conversation is too long for the model to process. Please start a new chat to continue."
          : isRetryable
            ? "The service is temporarily busy or timed out. Please wait a moment and try again."
            : "Sorry, something went wrong. Please try again."
        setMessages((prev) => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: displayMessage,
          }
          return updated
        })
      }
    } finally {
      abortControllerRef.current = null
      setIsLoading(false)
      onSendComplete?.()
    }
  }, [sessionId, mode, deckId, isLoading, auth.user?.access_token, auth.user?.profile?.sub, onToolEvent, onSendComplete])

  return { messages, setMessages, isLoading, sendMessage, stopGeneration, messagesRef }
}
