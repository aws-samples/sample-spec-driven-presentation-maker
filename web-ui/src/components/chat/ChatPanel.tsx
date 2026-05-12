// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel — Chat interface orchestrator.
 *
 * Delegates streaming to useChatStream, input to ChatInput.
 * Retains: history loading, reconnect, @mentions, Options, side effects.
 */

"use client"

import { useEffect, useRef, useState, useImperativeHandle, forwardRef, useCallback, useMemo } from "react"
import { useAuth } from "@/hooks/useAuth"
import { IS_LOCAL } from "@/lib/mode"
import { buildAttachedMarkers } from "@/lib/attachmentMarker"
import { generateSessionId, setAgentConfig } from "@/services/agentCoreService"
import { getChatHistory, patchDeck } from "@/services/deckService"
import type { UploadedFile } from "@/services/uploadService"
import { useChatStream, type Message, type ToolUseCallbackData } from "@/hooks/useChatStream"
import { ChatInput, type ChatInputHandle } from "./ChatInput"
import { ChatMessage, ToolUse } from "./ChatMessage"
import { McpStatusBar, McpServerStatus } from "./McpStatusBar"
import { FileDropZone } from "./FileDropZone"
import { useIsMobile } from "@/hooks/UseMobile"
import { Send, ChevronRight } from "lucide-react"
import { ModeSelector } from "./ModeSelector"
import { usePreferences } from "@/hooks/usePreferences"

interface ChatPanelProps {
  deckId: string
  deckName?: string
  chatSessionId?: string
  slideSlugs?: string[]
  onDeckCreated?: (deckId: string) => void
  onPreviewInvalidated?: () => void
  onWorkflowPhase?: (phase: string) => void
}

/** Handle exposed to parent for inserting text at cursor position. */
export interface ChatPanelHandle {
  insertAtCursor: (text: string) => void
}

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel({ deckId, deckName, chatSessionId, slideSlugs, onDeckCreated, onPreviewInvalidated, onWorkflowPhase }, ref) {
  // --- Session ---
  const [sessionId, setSessionId] = useState(() => {
    if (chatSessionId) return chatSessionId
    if (deckId === "new") return generateSessionId()
    return deckId.padEnd(36, "0")
  })
  useEffect(() => { if (chatSessionId && chatSessionId !== sessionId) setSessionId(chatSessionId) }, [chatSessionId])

  // --- Config ---
  const [configLoaded, setConfigLoaded] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [reconnectLoading, setReconnectLoading] = useState(false)

  // --- Options ---
  const [optionsOpen, setOptionsOpen] = useState(false)
  const { fetchWebImages, setFetchWebImages, parallelAgents, setParallelAgents, agentMode, setAgentMode } = usePreferences()

  // --- Refs ---
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)
  const reconnectingRef = useRef(false)
  const currentDeckId = useRef(deckId)
  currentDeckId.current = deckId

  const auth = useAuth()
  const isMobile = useIsMobile()

  /** Persist chat messages to disk (Local mode only). */
  const saveLocalChat = useCallback((overrideDeckId?: string) => {
    const did = overrideDeckId || currentDeckId.current
    if (!IS_LOCAL || !did || reconnectingRef.current) return
    fetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deckId: did, messages: stream.messagesRef.current }),
    }).catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- Tool event handler (side effects) ---
  const handleToolEvent = useCallback((toolName: string, toolUseData: ToolUseCallbackData | undefined) => {
    const idToken = auth.user?.id_token

    // Deck created
    if (toolUseData?.completed && toolUseData?.result?.deckId && onDeckCreated) {
      const resultDeckId = String(toolUseData.result.deckId)
      if (idToken) patchDeck(resultDeckId, { chatSessionId: sessionId }, idToken).catch(() => {})
      onDeckCreated(resultDeckId)
      saveLocalChat(resultDeckId)
    }

    // Preview invalidated
    if (toolUseData?.completed && (toolName === "generate_pptx" || toolName.endsWith("_generate_pptx")) && onPreviewInvalidated) {
      onPreviewInvalidated()
    }

    // Workflow phase detection
    if (onWorkflowPhase && (toolName === "read_workflows" || toolName.endsWith("_read_workflows"))) {
      const names = (toolUseData?.input?.names || []) as string[]
      const first = names[0] || ""
      if (first.includes("briefing")) onWorkflowPhase("brief")
      else if (first.includes("outline")) onWorkflowPhase("outline")
      else if (first.includes("art-direction")) onWorkflowPhase("artDirection")
      else if (first.includes("compose")) onWorkflowPhase("slides")
    }
    if (onWorkflowPhase && (toolName === "compose_slides" || toolName.endsWith("_compose_slides"))) {
      onWorkflowPhase("slides")
      saveLocalChat()
    }

    // Save on compose stream events
    if (toolUseData?.stream) {
      const d = toolUseData.data || {}
      if (d.status === "starting" || d.status === "done" || d.toolResult) {
        setTimeout(() => saveLocalChat(), 100)
      }
    }

    // Save after tool completed
    if (toolUseData?.completed) setTimeout(() => saveLocalChat(), 100)

    // Save after tool started (ensures compose_slides is persisted)
    if (!toolUseData?.completed && !toolUseData?.stream) setTimeout(() => saveLocalChat(), 100)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, auth.user?.id_token, onDeckCreated, onPreviewInvalidated, onWorkflowPhase])

  // --- useChatStream ---
  const mode = agentMode === "vibe" ? "vibe" : (parallelAgents ? "separated" : "single")
  const stream = useChatStream({
    sessionId,
    mode,
    deckId: currentDeckId.current !== "new" ? currentDeckId.current : undefined,
    onToolEvent: handleToolEvent,
    onSendComplete: () => saveLocalChat(),
  })

  // --- Ref handle ---
  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      chatInputRef.current?.insertAtCursor(text)
    },
  }), [])

  // --- Load agent config (cloud only) ---
  useEffect(() => {
    if (IS_LOCAL) { setConfigLoaded(true); return }
    async function loadConfig() {
      try {
        const response = await fetch("/aws-exports.json")
        const config = await response.json()
        await setAgentConfig(config.agentRuntimeArn, config.awsRegion || "us-east-1")
        setConfigLoaded(true)
      } catch (err) {
        console.error("Failed to load agent config:", err)
      }
    }
    loadConfig()
  }, [])

  // --- Load chat history ---
  useEffect(() => {
    async function loadHistory() {
      const idToken = auth.user?.id_token
      if (!IS_LOCAL && !idToken) return
      if (!sessionId) return
      setHistoryLoading(true)
      try {
        const history = await getChatHistory(sessionId, idToken ?? "", deckId || undefined)
        if (history.length > 0) {
          // Local mode: .chat.json is already in ChatPanel's internal format
          if (IS_LOCAL && (history[0] as unknown as Record<string, unknown>)?.toolUses !== undefined) {
            stream.setMessages(history.map((m) => {
              const raw = m as unknown as Record<string, unknown>
              return {
                role: ((raw.role as string) || "assistant") as "user" | "assistant",
                content: (typeof raw.content === "string" ? raw.content : "") as string,
                toolUses: (raw.toolUses as ToolUse[]) || [],
                blocks: (raw.blocks as ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[]) || undefined,
              }
            }))
            return
          }
          const parsed: Message[] = []
          for (const m of history) {
            let text = ""
            const toolUses: ToolUse[] = []
            const snippets: { label: string; text: string }[] = []

            if (typeof m.content === "string") {
              text = m.content.replace(/<!--sdpm:[^>]*-->\n?/g, "")
            } else if (Array.isArray(m.content)) {
              const contentBlocks = m.content as unknown as Record<string, unknown>[]
              if (m.role === "user" && contentBlocks.some((b) => b.toolResult)) {
                for (const block of contentBlocks) {
                  const b = block
                  if (b.toolResult) {
                    const tr = b.toolResult as Record<string, unknown>
                    const tuId = tr.toolUseId as string
                    const status = (tr.status as string) || "success"
                    let resultText = ""
                    for (const c of (tr.content as Record<string, unknown>[]) || []) {
                      if (c.text) resultText += c.text as string
                    }
                    if (parsed.length > 0) {
                      const prev = parsed[parsed.length - 1]
                      if (prev.role === "assistant") {
                        const matchedTool = prev.toolUses.find((t) => t.toolUseId === tuId)
                        if (matchedTool) {
                          matchedTool.status = status as "success" | "error"
                          try { matchedTool.result = JSON.parse(resultText) } catch { matchedTool.result = resultText as unknown as Record<string, unknown> }
                        }
                        if (prev.blocks) {
                          for (const bl of prev.blocks) {
                            if (bl.type === "tool" && bl.tool.toolUseId === tuId) {
                              bl.tool.status = status as "success" | "error"
                              try { bl.tool.result = JSON.parse(resultText) } catch { bl.tool.result = resultText as unknown as Record<string, unknown> }
                            }
                          }
                        }
                      }
                    }
                  }
                }
                continue
              }

              for (const block of contentBlocks) {
                const b = block
                if (b.toolUse) {
                  const tu = b.toolUse as Record<string, unknown>
                  toolUses.push({
                    toolUseId: (tu.toolUseId as string) || "",
                    name: (tu.name as string) || "",
                    input: (tu.input as Record<string, unknown>) || {},
                  })
                } else if (b.text && toolUses.length === 0) {
                  const cleaned = (b.text as string).replace(/<!--sdpm:[^>]*-->\n?/g, "")
                  if (cleaned) text += (text ? "\n" : "") + cleaned
                }
              }
            }
            if (!text.trim() && toolUses.length === 0) continue
            const blocks: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] = []
            if (m.role === "assistant" && Array.isArray(m.content)) {
              for (const block of m.content) {
                const b = block as Record<string, unknown>
                if (b.text) {
                  blocks.push({ type: "text", text: b.text as string })
                } else if (b.toolUse) {
                  const tu = b.toolUse as Record<string, unknown>
                  blocks.push({ type: "tool", tool: {
                    toolUseId: (tu.toolUseId as string) || "",
                    name: (tu.name as string) || "",
                    input: (tu.input as Record<string, unknown>) || {},
                  }})
                }
              }
            }
            parsed.push({
              role: m.role as "user" | "assistant",
              content: text,
              toolUses,
              blocks: blocks.length > 0 ? blocks : undefined,
              snippets: snippets.length > 0 ? snippets : undefined,
              ...((m.role === "user") && (() => {
                const attRe = /\[Attached:\s*(.+?)\s*\(uploadId:\s*[^)]+\)\]/g
                const atts: { fileName: string; fileType: string }[] = []
                let am: RegExpExecArray | null
                while ((am = attRe.exec(text)) !== null) {
                  const fn = am[1]
                  const ext = fn.split(".").pop()?.toLowerCase() || ""
                  const mimeMap: Record<string, string> = { pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation", pdf: "application/pdf", png: "image/png", json: "application/json", md: "text/markdown", txt: "text/plain" }
                  atts.push({ fileName: fn, fileType: mimeMap[ext] || "application/octet-stream" })
                }
                return atts.length > 0 ? { attachments: atts } : {}
              })()),
            })
          }
          if (parsed.length > 0) stream.setMessages(parsed)
        }
      } finally {
        setHistoryLoading(false)
      }
    }
    if (auth.isAuthenticated) loadHistory()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, auth.isAuthenticated])

  // --- Reconnect to running background session (Local mode) ---
  useEffect(() => {
    if (!IS_LOCAL || !deckId || deckId === "new") return
    let es: EventSource | null = null
    let completion = ""
    const toolPositions = new Map<string, number>()
    const toolOrder: string[] = []

    function buildBlocks(text: string, toolUses: ToolUse[]) {
      const blocks: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] = []
      const toolMap = new Map(toolUses.map(t => [t.toolUseId, t]))
      let textStart = 0
      for (const id of toolOrder) {
        const pos = toolPositions.get(id) ?? textStart
        const tool = toolMap.get(id)
        if (!tool) continue
        const slice = text.slice(textStart, pos)
        if (slice) blocks.push({ type: "text", text: slice })
        blocks.push({ type: "tool", tool })
        textStart = pos
      }
      const trailing = text.slice(textStart)
      if (trailing) blocks.push({ type: "text", text: trailing })
      return blocks
    }

    const timer = setTimeout(async () => {
      const sid = sessionId
      if (!sid) return
      try {
        const check = await fetch(`/api/agent/stream?sessionId=${encodeURIComponent(sid)}`)
        const ct = check.headers.get("content-type") || ""
        try { check.body?.getReader()?.cancel() } catch {}
        if (!ct.includes("text/event-stream")) return
      } catch { return }

      setReconnectLoading(true)

      const { parseStreamingChunk, resetParserState } = await import("@/services/strandsParser")
      if (resetParserState) resetParserState()

      reconnectingRef.current = true
      es = new EventSource(`/api/agent/stream?sessionId=${encodeURIComponent(sid)}`)

      let receivedData = false
      let replayDone = false
      es.onmessage = (event) => {
        if (!receivedData) { receivedData = true }
        if (!replayDone && toolOrder.length > 0) {
          replayDone = true
          reconnectingRef.current = false
          setTimeout(() => saveLocalChat(), 200)
        }
        const line = "data: " + event.data
        completion = parseStreamingChunk(
          line,
          completion,
          (streamed: string) => {
            stream.setMessages((prev) => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.role === "assistant") {
                const hasPositions = toolOrder.length > 0
                const blocks = hasPositions ? buildBlocks(streamed, last.toolUses) : last.blocks
                updated[updated.length - 1] = { ...last, content: streamed, ...(blocks ? { blocks } : {}) }
                return updated
              }
              return [...prev, { role: "assistant" as const, content: streamed, blocks: [{ type: "text" as const, text: streamed }], toolUses: [] }]
            })
          },
          (toolName: string, toolUseData: ToolUseCallbackData | undefined) => {
            if (toolUseData && 'started' in toolUseData && (toolUseData as Record<string, unknown>).started) {
              const tuId = toolUseData.toolUseId || ""
              toolPositions.set(tuId, completion.length)
              if (!toolOrder.includes(tuId)) toolOrder.push(tuId)
              stream.setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (!last || last.role !== "assistant") return prev
                if (last.toolUses.some((t: ToolUse) => t.toolUseId === tuId)) return prev
                const newTool = { toolUseId: tuId, name: toolName, input: toolUseData.input || {} }
                const newToolUses = [...last.toolUses, newTool]
                const blocks = buildBlocks(last.content, newToolUses)
                updated[updated.length - 1] = { ...last, toolUses: newToolUses, blocks }
                return updated
              })
            }
            if (toolUseData?.completed) {
              stream.setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (!last || last.role !== "assistant") return prev
                const newToolUses = last.toolUses.map((t: ToolUse) =>
                  t.toolUseId === toolUseData.toolUseId ? { ...t, status: "success" as const, result: toolUseData.result } : t
                )
                updated[updated.length - 1] = { ...last, toolUses: newToolUses }
                return updated
              })
              saveLocalChat()
            }
            if (toolUseData?.stream && toolUseData?.toolUseId) {
              const d = (toolUseData as Record<string, unknown>).data as Record<string, unknown> || {}
              stream.setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (!last || last.role !== "assistant") return prev
                const idx = last.toolUses.findIndex((t: ToolUse) => t.toolUseId === toolUseData.toolUseId)
                if (idx < 0) return prev
                const newToolUses = [...last.toolUses]
                const existing = newToolUses[idx].streamMessages || []
                let next: typeof existing
                if (d.toolResult) {
                  next = existing.map((e: Record<string, unknown>) =>
                    e.toolUseId === d.toolResult ? { ...e, status: d.toolStatus || "success" } : e
                  )
                } else if (d.tool) {
                  const existingIdx = existing.findIndex((e: Record<string, unknown>) => e.toolUseId === d.toolUseId)
                  if (existingIdx < 0) {
                    next = [...existing, { tool: d.tool, group: d.group, slugs: d.slugs, toolUseId: d.toolUseId }]
                  } else { next = existing }
                } else if (d.status) {
                  next = [...existing, { status: d.status, group: d.group, slugs: d.slugs, total_groups: d.total_groups }]
                } else { return prev }
                newToolUses[idx] = { ...newToolUses[idx], streamMessages: next }
                const blocks = buildBlocks(last.content, newToolUses)
                updated[updated.length - 1] = { ...last, toolUses: newToolUses, blocks }
                return updated
              })
              if (d.status === "starting" || d.status === "done") saveLocalChat()
            }
          },
        )
      }

      es.onerror = () => {
        if (es?.readyState === EventSource.CLOSED) {
          reconnectingRef.current = false
          setReconnectLoading(false)
        }
      }
    }, 800)

    return () => { clearTimeout(timer); es?.close(); reconnectingRef.current = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deckId])

  // --- Auto-scroll ---
  useEffect(() => {
    if (shouldAutoScroll.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [stream.messages])

  // --- Message pre-processing and send ---
  const handleSend = useCallback((
    text: string,
    uploadedFiles: UploadedFile[],
    snippets: { label: string; text: string }[],
    attachments: { fileName: string; fileType: string }[],
  ) => {
    if (!configLoaded) return

    let fullMessage = text

    if (uploadedFiles.length > 0) {
      fullMessage = `${buildAttachedMarkers(uploadedFiles)}\n\n${fullMessage}`
    }
    if (snippets.length > 0) {
      const snippetInfo = snippets.map((s) => `---snippet---\n${s.text}\n---/snippet---`).join("\n\n")
      fullMessage = `${fullMessage}\n\n${snippetInfo}`
    }
    if (fetchWebImages) {
      fullMessage = `<!--sdpm:include_images=true-->\n${fullMessage}`
    }

    stream.sendMessage(fullMessage, uploadedFiles, snippets, attachments, { displayContent: text })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configLoaded, deckId, fetchWebImages, stream.sendMessage])

  // --- Compose in-flight detection (for stop tooltip) ---
  const composeInFlight = useMemo(() => {
    if (!stream.isLoading) return false
    const last = stream.messages[stream.messages.length - 1]
    if (!last || last.role !== "assistant") return false
    const lastTool = last.toolUses[last.toolUses.length - 1]
    if (!lastTool || lastTool.status) return false
    return lastTool.name === "compose_slides" || lastTool.name.endsWith("_compose_slides")
  }, [stream.isLoading, stream.messages])

  const isLoading = stream.isLoading || reconnectLoading
  const isInitial = stream.messages.length === 0 && !historyLoading

  return (
    <FileDropZone onFiles={(files) => chatInputRef.current?.addFiles(Array.from(files))} disabled={stream.isLoading} className="flex flex-col h-full">
      {/* Messages area */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-4 py-4" role="log" aria-label="Chat messages"
        onScroll={() => {
          const el = scrollContainerRef.current
          if (!el) return
          shouldAutoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
      >
        {historyLoading ? (
          <div className="space-y-4 animate-pulse">
            {[0.6, 1, 0.75].map((w, i) => (
              <div key={i} className={i % 2 === 0 ? "flex justify-end" : "flex gap-2.5"}>
                {i % 2 !== 0 && <div className="w-6 h-6 rounded-full bg-white/[0.06] flex-none" />}
                <div className="rounded-2xl bg-white/[0.04] h-10" style={{ width: `${w * 70}%` }} />
              </div>
            ))}
          </div>
        ) : isInitial ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <div className="w-12 h-12 rounded-2xl flex items-center justify-center bg-brand-teal-soft mb-5">
              <Send className="h-5 w-5 text-brand-teal" />
            </div>
            <h2 className="text-[22px] font-bold tracking-[-0.03em] text-brand-teal mb-1">Let&apos;s present</h2>
            <p className="text-sm text-foreground-muted leading-relaxed mb-8">
              Drop a URL, paste notes, or describe your idea
            </p>
            {parallelAgents && <ModeSelector value={agentMode} onChange={setAgentMode} />}
          </div>
        ) : (
          <div className="space-y-4">
            {(() => {
              const lastUserIdx = stream.messages.findLastIndex((m) => m.role === "user")
              return stream.messages.map((msg, i) => (
              <div key={i}>
                {msg.mcpStatus && (
                  <div className="mb-2 ml-10">
                    <McpStatusBar servers={msg.mcpStatus} />
                  </div>
                )}
                <ChatMessage
                  role={msg.role}
                  content={msg.content}
                  toolUses={msg.toolUses}
                  blocks={msg.blocks}
                  snippets={msg.snippets}
                  attachments={msg.attachments}
                  isStreaming={stream.isLoading && i === stream.messages.length - 1}
                  idToken={auth.user?.id_token}
                  accessToken={auth.user?.access_token}
                  deckSlugs={slideSlugs}
                  sessionId={sessionId}
                  onSend={(text: string) => handleSend(text, [], [], [])}
                  hearingDisabled={i < lastUserIdx}
                />
              </div>
            ))
            })()}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <ChatInput
          ref={chatInputRef}
          onSend={handleSend}
          isLoading={isLoading}
          onStop={stream.stopGeneration}
          disabled={!configLoaded || reconnectLoading}
          placeholder={isMobile ? "Ask anything…" : "Ask anything…  ⌘↵ send"}
          idToken={auth.user?.id_token}
          sessionId={sessionId}
          deckId={deckId}
          stopTitle={composeInFlight ? "Force stop — partial report may be lost" : undefined}
        >
          {/* Options expander */}
          <div className="px-2">
            <button
              type="button"
              onClick={() => setOptionsOpen((v) => !v)}
              className="flex items-center gap-1 text-[11px] text-foreground-muted hover:text-foreground transition-colors py-1"
            >
              <ChevronRight className={`h-3 w-3 transition-transform duration-200 ${optionsOpen ? "rotate-90" : ""}`} />
              Options
            </button>
            {optionsOpen && (
              <div className="flex flex-col gap-2 pb-2 pl-1">
                {!IS_LOCAL && (
                <label className="group flex items-center justify-between gap-3 rounded-lg px-3 py-2 cursor-pointer
                  bg-white/[0.02] hover:bg-white/[0.05] transition-colors">
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="text-xs text-foreground-secondary font-medium select-none">Fetch web images</span>
                    <span className="text-[11px] text-foreground-muted select-none leading-snug">Include images from websites in presentations</span>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={fetchWebImages}
                    onClick={() => setFetchWebImages(!fetchWebImages)}
                    className={`relative flex-none w-9 h-5 rounded-full transition-colors duration-200 ${
                      fetchWebImages ? "bg-brand-teal" : "bg-white/[0.1]"
                    }`}
                  >
                    <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                      fetchWebImages ? "translate-x-4" : ""
                    }`} />
                  </button>
                </label>
                )}

                <label className="group flex items-center justify-between gap-3 rounded-lg px-3 py-2 cursor-pointer
                  bg-white/[0.02] hover:bg-white/[0.05] transition-colors">
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="text-xs text-foreground-secondary font-medium select-none flex items-center gap-2">
                      Parallel agents
                      <span className="inline-flex items-center gap-1 px-1.5 py-px rounded-full text-[11px] font-semibold tracking-wide
                        bg-brand-amber-soft text-brand-amber border border-brand-amber/25">
                        🧪 Experimental
                      </span>
                    </span>
                    <span className="text-[11px] text-foreground-muted select-none leading-snug">Multiple composer agents generate slides in parallel</span>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={parallelAgents}
                    onClick={() => setParallelAgents(!parallelAgents)}
                    className={`relative flex-none w-9 h-5 rounded-full transition-colors duration-200 ${
                      parallelAgents ? "bg-brand-teal" : "bg-white/[0.1]"
                    }`}
                  >
                    <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                      parallelAgents ? "translate-x-4" : ""
                    }`} />
                  </button>
                </label>
              </div>
            )}
          </div>
        </ChatInput>
    </FileDropZone>
  )
})
