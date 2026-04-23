// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel — Chat interface with streaming via AgentCore SSE.
 *
 * Key behaviors:
 * - Send: ⌘+Enter (Mac) / Ctrl+Enter (Win). Enter = newline.
 * - IME-safe: compositionstart/end tracking for Japanese/CJK input.
 * - Textarea stays focused and editable during agent response.
 * - Only the send button shows loading state.
 * - Tool executions shown as structured indicators, not inline text.
 * - File upload via + menu, drag-and-drop, ⌘V paste.
 * - @mentions for slide and deck references.
 */

"use client"

import { useEffect, useRef, useState, useImperativeHandle, forwardRef, FormEvent, KeyboardEvent, useCallback, useMemo } from "react"
import { useAuth } from "@/hooks/useAuth"
import { IS_LOCAL } from "@/lib/mode"
import { invokeAgentCore, generateSessionId, setAgentConfig, stopRuntimeSession } from "@/services/agentCoreService"
import { getChatHistory, listDecks, patchDeck, DeckSummary } from "@/services/deckService"
import { uploadFile, validateFile, canAddMoreFiles, UploadedFile } from "@/services/uploadService"
import { useCompositionSafe } from "@/hooks/useCompositionSafe"
import { ChatMessage, ToolUse } from "./ChatMessage"
import { McpStatusBar, McpServerStatus } from "./McpStatusBar"
import { MentionOverlay } from "./MentionOverlay"
import { MentionPopup, MentionItem } from "./MentionPopup"
import { PlusMenu } from "./PlusMenu"
import { AttachmentPreview, Attachment, SnippetAttachment } from "./AttachmentPreview"
import { FileDropZone } from "./FileDropZone"
import { SnippetInput } from "./SnippetInput"
import { useIsMobile } from "@/hooks/UseMobile"
import { Send, Square, ChevronRight } from "lucide-react"
import { ModeSelector } from "./ModeSelector"
import { usePreferences } from "@/hooks/usePreferences"
import { toast } from "sonner"

interface Message {
  role: "user" | "assistant"
  content: string
  toolUses: ToolUse[]
  /** Ordered sequence of text and tool blocks for inline display. */
  blocks?: { type: "text"; text: string }[] | { type: "tool"; tool: ToolUse }[]
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
  mcpStatus?: McpServerStatus[]
}

/** Shape of tool-use callback data from the agent streaming API. */
interface ToolUseCallbackData {
  toolUseId?: string
  completed?: boolean
  status?: "success" | "error"
  result?: Record<string, unknown>
  input?: Record<string, unknown>
  /** Tool streaming progress event. */
  stream?: boolean
  data?: Record<string, unknown>
}

interface ChatPanelProps {
  deckId: string
  deckName?: string
  chatSessionId?: string
  slidePreviewUrls?: (string | null)[]
  /** Current deck slide IDs — forwarded to ComposeCard for slug existence rendering. */
  slideSlugs?: string[]
  onDeckCreated?: (deckId: string) => void
  onPreviewInvalidated?: () => void
  onWorkflowPhase?: (phase: string) => void
}

/** Handle exposed to parent for inserting text at cursor position. */
export interface ChatPanelHandle {
  insertAtCursor: (text: string) => void
}

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel({ deckId, deckName, chatSessionId, slidePreviewUrls, slideSlugs, onDeckCreated, onPreviewInvalidated, onWorkflowPhase }, ref) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [mentionVisible, setMentionVisible] = useState(false)
  const [mentionQuery, setMentionQuery] = useState("")
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([])
  const [allDecks, setAllDecks] = useState<DeckSummary[]>([])
  const [snippetOpen, setSnippetOpen] = useState(false)
  const [snippets, setSnippets] = useState<SnippetAttachment[]>([])
  const [editingSnippetId, setEditingSnippetId] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState(() => {
    if (chatSessionId) return chatSessionId
    if (deckId === "new") return generateSessionId()
    return deckId.padEnd(36, "0")
  })

  useEffect(() => {
    if (chatSessionId && chatSessionId !== sessionId) {
      setSessionId(chatSessionId)
    }
  }, [chatSessionId])

  const [configLoaded, setConfigLoaded] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const mentionPopupRef = useRef<{ _handleKeyDown?: (e: KeyboardEvent) => boolean } | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const currentDeckId = useRef(deckId)
  currentDeckId.current = deckId
  const auth = useAuth()
  const { onCompositionStart, onCompositionEnd, getIsComposing } = useCompositionSafe()
  const isMobile = useIsMobile()
  const { fetchWebImages, setFetchWebImages, parallelAgents, setParallelAgents, agentMode, setAgentMode } = usePreferences()
  const [optionsOpen, setOptionsOpen] = useState(false)

  /**
   * Insert text at the current cursor position in the textarea.
   * Exposed to parent via ref.
   */
  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      const ta = textareaRef.current
      if (!ta) return
      const start = ta.selectionStart
      const end = ta.selectionEnd
      const before = input.slice(0, start)
      const after = input.slice(end)
      const newValue = before + text + after
      setInput(newValue)
      requestAnimationFrame(() => {
        ta.focus()
        const pos = start + text.length
        ta.setSelectionRange(pos, pos)
      })
    },
  }), [input])

  // Load agent config (cloud only — local mode uses API routes)
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

  // Load chat history
  useEffect(() => {
    async function loadHistory() {
      const idToken = auth.user?.id_token
      if (!idToken || !sessionId) return
      setHistoryLoading(true)
      try {
      const history = await getChatHistory(sessionId, idToken, deckId || undefined)
      if (history.length > 0) {
        const parsed: typeof messages = []
        for (const m of history) {
          let text = ""
          const toolUses: ToolUse[] = []
          const snippets: { label: string; text: string }[] = []

          if (typeof m.content === "string") {
            text = m.content.replace(/<!--sdpm:[^>]*-->\n?/g, "")
          } else if (Array.isArray(m.content)) {
            // toolResult messages: attach result to matching toolUse in previous assistant
            if (m.role === "user" && m.content.some((b: Record<string, unknown>) => b.toolResult)) {
              for (const block of m.content) {
                const b = block as Record<string, unknown>
                if (b.toolResult) {
                  const tr = b.toolResult as Record<string, unknown>
                  const tuId = tr.toolUseId as string
                  const status = (tr.status as string) || "success"
                  let resultText = ""
                  for (const c of (tr.content as Record<string, unknown>[]) || []) {
                    if (c.text) resultText += c.text as string
                  }
                  // Find matching toolUse in previous assistant and set result
                  if (parsed.length > 0) {
                    const prev = parsed[parsed.length - 1]
                    if (prev.role === "assistant") {
                      const matchedTool = prev.toolUses.find((t) => t.toolUseId === tuId)
                      if (matchedTool) {
                        matchedTool.status = status
                        try { matchedTool.result = JSON.parse(resultText) } catch { matchedTool.result = resultText }
                      }
                      // Update blocks too
                      if (prev.blocks) {
                        for (const bl of prev.blocks) {
                          if (bl.type === "tool" && bl.tool.toolUseId === tuId) {
                            bl.tool.status = status
                            try { bl.tool.result = JSON.parse(resultText) } catch { bl.tool.result = resultText }
                          }
                        }
                      }
                    }
                  }
                }
              }
              continue
            }

            for (const block of m.content) {
              const b = block as Record<string, unknown>
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
          // Build blocks for inline tool display (same as streaming)
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
        if (parsed.length > 0) setMessages(parsed)
      }
      } finally {
        setHistoryLoading(false)
      }
    }
    if (auth.isAuthenticated) loadHistory()
  }, [sessionId, auth.isAuthenticated])

  // Load deck list for @mentions
  useEffect(() => {
    async function loadDecks() {
      const idToken = auth.user?.id_token
      if (!idToken) return
      const data = await listDecks(idToken)
      setAllDecks(data.decks)
    }
    if (auth.isAuthenticated) loadDecks()
  }, [auth.isAuthenticated])

  useEffect(() => {
    if (shouldAutoScroll.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (ta) {
      ta.style.height = "0px"
      ta.style.height = ta.scrollHeight + "px"
    }
  }, [input])

  // Build mention items from current deck slides + other decks
  useEffect(() => {
    const items: MentionItem[] = []

    // Current deck slides with preview URLs
    if (slidePreviewUrls) {
      const did = deckId !== "new" ? deckId : null
      const displayName = deckName || "Deck"
      slidePreviewUrls.forEach((url, i) => {
        items.push({
          label: `Page ${i + 1}`,
          insertText: did
            ? `@${displayName}(#${did}):Page ${i + 1}`
            : `@Page ${i + 1}`,
          type: "slide",
          page: i + 1,
          previewUrl: url,
        })
      })
    }

    // Other decks with thumbnails
    allDecks
      .filter((d) => d.deckId !== deckId)
      .forEach((d) => {
        items.push({
          label: d.name,
          insertText: `@${d.name}(#${d.deckId})`,
          type: "deck",
          deckId: d.deckId,
          previewUrl: d.thumbnailUrl,
        })
      })

    setMentionItems(items)
  }, [slidePreviewUrls, allDecks, deckId])

  /**
   * Handle file selection from + menu or drag-and-drop.
   *
   * @param files - FileList from input or drop event
   */
  const handleFiles = useCallback((files: FileList) => {
    const currentCount = attachments.length
    const newFiles = Array.from(files)

    for (const file of newFiles) {
      if (!canAddMoreFiles(currentCount + attachments.length)) {
        toast.error("Maximum 5 files can be attached at once.")
        break
      }

      const error = validateFile(file)
      if (error) {
        toast.error(error)
        continue
      }

      const id = crypto.randomUUID()
      setAttachments((prev) => [...prev, { id, file, status: "pending" }])
    }
  }, [attachments.length])

  /**
   * Remove an attachment by ID.
   *
   * @param id - Attachment identifier
   */
  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  /**
   * Detect @ input for mention popup.
   *
   * @param value - Current textarea value
   */
  const handleInputChange = (value: string) => {
    setInput(value)

    const ta = textareaRef.current
    if (!ta) return

    const cursorPos = ta.selectionStart
    const textBeforeCursor = value.slice(0, cursorPos)

    // Check if we're in a mention context (@ followed by non-space chars)
    const mentionMatch = textBeforeCursor.match(/@(\w*)$/)
    if (mentionMatch) {
      setMentionVisible(true)
      setMentionQuery(mentionMatch[1])
    } else {
      setMentionVisible(false)
      setMentionQuery("")
    }
  }

  /**
   * Handle mention selection from popup.
   *
   * @param item - Selected mention item
   */
  const handleMentionSelect = (item: MentionItem) => {
    const ta = textareaRef.current
    if (!ta) return

    const cursorPos = ta.selectionStart
    const textBeforeCursor = input.slice(0, cursorPos)
    const mentionStart = textBeforeCursor.lastIndexOf("@")

    if (mentionStart >= 0) {
      const before = input.slice(0, mentionStart)
      const after = input.slice(cursorPos)
      const newValue = before + item.insertText + " " + after
      setInput(newValue)

      requestAnimationFrame(() => {
        ta.focus()
        const pos = mentionStart + item.insertText.length + 1
        ta.setSelectionRange(pos, pos)
      })
    }

    setMentionVisible(false)
  }

  /**
   * Upload all pending attachments and send the message.
   *
   * @param userMessage - The text to send
   */
  const handleSend = async (userMessage: string) => {
    if ((!userMessage.trim() && attachments.length === 0 && snippets.length === 0) || !configLoaded || isLoading) return

    const idToken = auth.user?.id_token
    const accessToken = auth.user?.access_token
    const userId = auth.user?.profile?.sub
    if (!accessToken || !userId || !idToken) return

    // Upload pending attachments
    const uploadedFiles: UploadedFile[] = []
    for (const att of attachments) {
      if (att.status === "pending") {
        try {
          setAttachments((prev) =>
            prev.map((a) => (a.id === att.id ? { ...a, status: "uploading" as const } : a)),
          )
          const result = await uploadFile(att.file, idToken, sessionId, deckId !== "new" ? deckId : undefined)
          uploadedFiles.push(result)
          setAttachments((prev) =>
            prev.map((a) => (a.id === att.id ? { ...a, status: "completed" as const, uploadId: result.uploadId } : a)),
          )
        } catch {
          setAttachments((prev) =>
            prev.map((a) => (a.id === att.id ? { ...a, status: "failed" as const, error: "Upload failed" } : a)),
          )
        }
      }
    }

    // Build message with attachment and snippet info
    // Resolve @mentions to agent-readable instructions
    let fullMessage = userMessage
      // @DeckName(#id):Page N — slide with deckId
      .replace(/@([^@(]+)\(#([^)]+)\):Page\s(\d+)/g, (_, name, did, page) =>
        `[Reference: Slide Page ${page} of deck "${name}" (deckId: ${did}). Use get_deck("${did}") to read slide content.]`)
      // @DeckName(#id) — deck reference
      .replace(/@([^@(]+)\(#([^)]+)\)/g, (_, name, did) =>
        `[Reference: Deck "${name}" (deckId: ${did}). Use get_deck("${did}") to read its content.]`)
      // Legacy: @Page N (no deckId)
      .replace(/@Page\s(\d+)/g, (_, page) => {
        const did = deckId !== "new" ? deckId : null
        return did
          ? `[Reference: Slide Page ${page} of current deck (deckId: ${did}). Use get_deck("${did}") to read slide content.]`
          : `[Reference: Slide Page ${page} of current deck]`
      })
    if (uploadedFiles.length > 0) {
      const fileInfo = uploadedFiles
        .map((f) => `[Attached: ${f.fileName} (uploadId: ${f.uploadId})]`)
        .join("\n")
      fullMessage = `${fileInfo}\n\n${fullMessage}`
    }
    if (snippets.length > 0) {
      const snippetInfo = snippets
        .map((s) => `---snippet---\n${s.text}\n---/snippet---`)
        .join("\n\n")
      fullMessage = `${fullMessage}\n\n${snippetInfo}`
    }
    if (fetchWebImages) {
      fullMessage = `<!--sdpm:include_images=true-->\n${fullMessage}`
    }

    const sentSnippets = snippets.map((s) => ({ label: s.label || "Text snippet", text: s.text }))
    const sentAttachments = uploadedFiles.map((f) => ({ fileName: f.fileName, fileType: f.fileType }))

    setMessages((prev) => [
      ...prev,
      { role: "user", content: userMessage, toolUses: [], snippets: sentSnippets.length > 0 ? sentSnippets : undefined, attachments: sentAttachments.length > 0 ? sentAttachments : undefined },
      { role: "assistant", content: "", toolUses: [] },
    ])
    setInput("")
    setAttachments([])
    setSnippets([])
    setIsLoading(true)

    const controller = new AbortController()
    abortControllerRef.current = controller

    requestAnimationFrame(() => textareaRef.current?.focus())

    try {
      let lastTextSnapshot = ""
      /** Map toolUseId → character position in cumulative text where tool was first seen. */
      const toolPositions = new Map<string, number>()
      /** Ordered list of toolUseIds in insertion order. */
      const toolOrder: string[] = []

      /**
       * Rebuild blocks array from cumulative text + tool positions.
       *
       * @param text - Cumulative streamed text
       * @param toolMap - Map of toolUseId → ToolUse data
       * @returns Ordered blocks array
       */
      function rebuildBlocks(text: string, toolMap: Map<string, ToolUse>): ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] {
        const result: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] = []
        let textStart = 0
        for (const id of toolOrder) {
          const pos = toolPositions.get(id) ?? textStart
          const tool = toolMap.get(id)
          if (!tool) continue
          const textSlice = text.slice(textStart, pos)
          if (textSlice) result.push({ type: "text", text: textSlice })
          result.push({ type: "tool", tool })
          textStart = pos
        }
        const trailing = text.slice(textStart)
        if (trailing) result.push({ type: "text", text: trailing })
        return result
      }

      await invokeAgentCore(
        fullMessage,
        sessionId,
        (streamed: string) => {
          lastTextSnapshot = streamed
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            const toolMap = new Map(last.toolUses.map((t) => [t.toolUseId, t]))
            const blocks = rebuildBlocks(streamed, toolMap)
            updated[updated.length - 1] = { ...last, content: streamed, blocks }
            return updated
          })
        },
        accessToken,
        userId,
        (toolName: string, toolUseData: ToolUseCallbackData | undefined) => {
          // MCP status event — show on first message, or when status changes
          if (toolName === '__mcp_status__' && toolUseData && 'mcpStatus' in toolUseData) {
            const incoming = (toolUseData as unknown as { mcpStatus: McpServerStatus[] }).mcpStatus
            setMessages((prev) => {
              // Find the last mcpStatus in history
              const lastStatus = [...prev].reverse().find((m) => m.mcpStatus)?.mcpStatus
              // Skip if identical to previous
              if (lastStatus && JSON.stringify(lastStatus) === JSON.stringify(incoming)) return prev
              const updated = [...prev]
              const last = updated[updated.length - 1]
              updated[updated.length - 1] = { ...last, mcpStatus: incoming }
              return updated
            })
            return
          }

          // Tool stream event — append progress to existing tool
          if (toolUseData?.stream && toolUseData?.toolUseId) {
            const d = toolUseData.data || {}
            setMessages((prev) => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              const idx = last.toolUses.findIndex((t) => t.toolUseId === toolUseData.toolUseId)
              if (idx < 0) return prev
              const newToolUses = [...last.toolUses]
              const existing = newToolUses[idx].streamMessages || []

              let next: typeof existing
              if (d.toolResult) {
                // Tool completed — update existing entry's status
                next = existing.map((e) =>
                  typeof e === "object" && e.toolUseId === d.toolResult
                    ? { ...e, status: d.toolStatus || "success" }
                    : e
                )
              } else if (d.tool) {
                // New sub-tool started (or update with input from hook)
                const existingIdx = existing.findIndex((e) => typeof e === "object" && e.toolUseId === d.toolUseId)
                if (existingIdx >= 0 && d.input) {
                  next = existing.map((e, idx) => idx === existingIdx ? { ...e, input: d.input } : e)
                } else if (existingIdx < 0) {
                  next = [...existing, { tool: d.tool, group: d.group, slugs: d.slugs, toolUseId: d.toolUseId, input: d.input }]
                } else {
                  return prev
                }
              } else if (d.status) {
                // Group status event
                next = [...existing, { status: d.status, group: d.group, slugs: d.slugs, total_groups: d.total_groups, done: d.done, total: d.total, summary: d.summary, message: d.message, attempt: d.attempt, error: d.error }]
              } else {
                return prev
              }

              newToolUses[idx] = { ...newToolUses[idx], streamMessages: next }
              const toolMap = new Map(newToolUses.map((t) => [t.toolUseId, t]))
              const blocks = rebuildBlocks(lastTextSnapshot, toolMap)
              updated[updated.length - 1] = { ...last, toolUses: newToolUses, blocks }
              return updated
            })
            return
          }

          // Tool result (completed) — detect deckId from any tool's result
          if (toolUseData?.completed && toolUseData?.result?.deckId && onDeckCreated) {
            // Link chat session to deck for history restore
            const resultDeckId = String(toolUseData.result.deckId)
            if (idToken) {
              patchDeck(resultDeckId, { chatSessionId: sessionId }, idToken).catch(() => {})
            }
            onDeckCreated(resultDeckId)
          }
          if (toolUseData?.completed && (toolName === "generate_pptx" || toolName.endsWith("_generate_pptx")) && onPreviewInvalidated) {
            onPreviewInvalidated()
          }

          // Tool result: update existing ToolUse with result/status
          if (toolUseData?.completed) {
            setMessages((prev) => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              const idx = last.toolUses.findIndex((t) => t.toolUseId === toolUseData.toolUseId)
              if (idx >= 0) {
                const newToolUses = [...last.toolUses]
                newToolUses[idx] = { ...newToolUses[idx], status: toolUseData.status, result: toolUseData.result }
                const toolMap = new Map(newToolUses.map((t) => [t.toolUseId, t]))
                const blocks = rebuildBlocks(lastTextSnapshot, toolMap)
                updated[updated.length - 1] = { ...last, toolUses: newToolUses, blocks }
              }
              return updated
            })
            return
          }

          const toolUse: ToolUse = {
            toolUseId: toolUseData?.toolUseId || crypto.randomUUID(),
            name: toolName,
            input: toolUseData?.input || {},
          }

          // Detect workflow phase from tool calls
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
          }

          // Record position only on first encounter
          if (!toolPositions.has(toolUse.toolUseId)) {
            toolPositions.set(toolUse.toolUseId, lastTextSnapshot.length)
            toolOrder.push(toolUse.toolUseId)
          }

          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]

            const existingIdx = last.toolUses.findIndex((t) => t.toolUseId === toolUse.toolUseId)
            const newToolUses = existingIdx >= 0
              ? last.toolUses.map((t, i) => i === existingIdx ? { ...t, ...toolUse, status: t.status, result: t.result } : t)
              : [...last.toolUses, toolUse]

            const toolMap = new Map(newToolUses.map((t) => [t.toolUseId, t]))
            const blocks = rebuildBlocks(lastTextSnapshot, toolMap)

            updated[updated.length - 1] = { ...last, content: lastTextSnapshot, blocks, toolUses: newToolUses }
            return updated
          })
        },
        controller.signal,
        agentMode === "vibe" ? "vibe" : (parallelAgents ? "separated" : "single"),
      )
    } catch (err) {
      // AbortError is expected when user clicks stop — don't show error
      if (err instanceof DOMException && err.name === "AbortError") {
        // Keep partial response as-is
      } else {
        setMessages((prev) => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: "Sorry, something went wrong. Please try again.",
          }
          return updated
        })
      }
    } finally {
      abortControllerRef.current = null
      setIsLoading(false)
      // Save chat messages to disk in local mode
      if (IS_LOCAL && currentDeckId.current) {
        fetch("/api/agent/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ deckId: currentDeckId.current, messages: messagesRef.current }),
        }).catch(() => {})
      }
    }
  }

  /**
   * Stop the current streaming response.
   * Aborts the fetch connection and calls StopRuntimeSession to immediately
   * terminate the AgentCore Runtime session (including all ThreadPool-based
   * composer agents inside the container).
   */
  const handleStop = () => {
    abortControllerRef.current?.abort()
    const token = auth.user?.access_token
    if (token) stopRuntimeSession(sessionId, token)
  }

  // Track whether compose_slides is the active in-flight tool — used only to
  // reshape the Stop tooltip. The button itself stays enabled so the user
  // always has a final-resort force stop.
  const composeInFlight = useMemo(() => {
    if (!isLoading) return false
    const last = messages[messages.length - 1]
    if (!last || last.role !== "assistant") return false
    const lastTool = last.toolUses[last.toolUses.length - 1]
    if (!lastTool || lastTool.status) return false
    return lastTool.name === "compose_slides" || lastTool.name.endsWith("_compose_slides")
  }, [isLoading, messages])

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    handleSend(input)
  }

  /**
   * Send behavior respects user preference.
   * sendWithEnter=true: Enter sends, Shift+Enter = newline.
   * sendWithEnter=false: ⌘/Ctrl+Enter sends, Enter = newline.
   * IME composition Enter is ignored.
   * Arrow keys and Enter are intercepted when mention popup is visible.
   */
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (getIsComposing(e)) return

    // Let mention popup handle navigation keys
    if (mentionVisible && (MentionPopup as unknown as { _handleKeyDown?: (e: KeyboardEvent) => boolean })._handleKeyDown?.(e)) {
      return
    }

    const canSend = input.trim() || attachments.length > 0 || snippets.length > 0
    const sendWithEnter = (() => { try { return JSON.parse(localStorage.getItem("sdpm-prefs") || "{}").sendWithEnter ?? false } catch { return false } })()

    if (sendWithEnter) {
      if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && canSend) {
        e.preventDefault()
        handleSend(input)
      }
    } else {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSend) {
        e.preventDefault()
        handleSend(input)
      }
    }
  }

  const handleSnippetRequest = () => {
    setSnippetOpen(true)
  }

  /**
   * Handle confirmed snippet text — add new or update existing.
   *
   * @param text - The snippet text
   */
  const handleSnippetConfirm = (text: string) => {
    if (editingSnippetId) {
      setSnippets((prev) => prev.map((s) => s.id === editingSnippetId ? { ...s, text } : s))
      setEditingSnippetId(null)
    } else {
      setSnippets((prev) => [...prev, { id: crypto.randomUUID(), text }])
    }
  }

  /**
   * Open snippet dialog for editing.
   *
   * @param id - Snippet identifier
   */
  const editSnippet = useCallback((id: string) => {
    setEditingSnippetId(id)
    setSnippetOpen(true)
  }, [])

  /**
   * Remove a snippet by ID.
   *
   * @param id - Snippet identifier
   */
  const removeSnippet = useCallback((id: string) => {
    setSnippets((prev) => prev.filter((s) => s.id !== id))
  }, [])

  const isInitial = messages.length === 0 && !historyLoading

  return (
    <FileDropZone onFiles={handleFiles} onLongTextPaste={handleSnippetConfirm} pasteDisabled={snippetOpen} disabled={isLoading}>
      <div className="flex flex-col h-full">
        <SnippetInput
          open={snippetOpen}
          onClose={() => { setSnippetOpen(false); setEditingSnippetId(null) }}
          onConfirm={handleSnippetConfirm}
          initialText={editingSnippetId ? snippets.find((s) => s.id === editingSnippetId)?.text : undefined}
        />
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-4 py-4" role="log" aria-label="Chat messages"
          onScroll={() => {
            const el = scrollContainerRef.current
            if (!el) return
            // Near bottom (within 80px) → re-enable auto-scroll
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
              <p className="text-[13px] text-foreground-muted leading-relaxed mb-8">
                Drop a URL, paste notes, or describe your idea
              </p>
              <ModeSelector value={agentMode} onChange={setAgentMode} />
            </div>
          ) : (
            <div className="space-y-4">
              {(() => {
                const lastUserIdx = messages.findLastIndex((m) => m.role === "user")
                return messages.map((msg, i) => (
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
                    isStreaming={isLoading && i === messages.length - 1}
                    idToken={auth.user?.id_token}
                    accessToken={auth.user?.access_token}
                    deckSlugs={slideSlugs}
                    sessionId={sessionId}
                    onSend={handleSend}
                    hearingDisabled={i < lastUserIdx}
                  />
                </div>
              ))
              })()}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="flex-none px-3 pb-6 pt-2 safe-bottom">
          <form
            onSubmit={handleSubmit}
            className="rounded-xl border border-white/[0.08] bg-background-raised search-glow"
          >
            <AttachmentPreview
              attachments={attachments}
              snippets={snippets}
              onRemove={removeAttachment}
              onRemoveSnippet={removeSnippet}
              onEditSnippet={editSnippet}
            />

            {/* Options expander */}
            <div className="px-2">
              <button
                type="button"
                onClick={() => setOptionsOpen((v) => !v)}
                className="flex items-center gap-1 text-[11px] text-foreground-muted hover:text-foreground transition-colors py-1"
              >
                <ChevronRight className={`h-3 w-3 transition-transform ${optionsOpen ? "rotate-90" : ""}`} />
                Options
              </button>
              {optionsOpen && (
                <div className="flex flex-col gap-1 pb-1.5 pl-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={fetchWebImages}
                      onChange={(e) => setFetchWebImages(e.target.checked)}
                      className="accent-[var(--color-brand-teal)] h-3.5 w-3.5"
                    />
                    <span className="text-[11px] text-foreground-muted select-none">
                      Fetch images from websites (may be used in presentations)
                    </span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={parallelAgents}
                      onChange={(e) => setParallelAgents(e.target.checked)}
                      className="accent-[var(--color-brand-teal)] h-3.5 w-3.5"
                    />
                    <span className="text-[11px] text-foreground-muted select-none">
                      Parallel agents (experimental) — SPEC + Composer with parallel slide generation
                    </span>
                  </label>
                </div>
              )}
            </div>

            <div className="flex items-end gap-2 px-2 py-2">
              <PlusMenu
                onFilesSelected={handleFiles}
                onSnippetRequest={handleSnippetRequest}
                disabled={isLoading}
              />

              <div className="flex-1 relative">
                <MentionPopup
                  ref={mentionPopupRef}
                  visible={mentionVisible}
                  query={mentionQuery}
                  items={mentionItems}
                  onSelect={handleMentionSelect}
                  onClose={() => setMentionVisible(false)}
                  position={{ top: 40, left: 0 }}
                  textareaRef={textareaRef}
                />
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onCompositionStart={onCompositionStart}
                  onCompositionEnd={onCompositionEnd}
                  placeholder={isMobile ? "Ask anything…" : "Ask anything…  ⌘↵ send"}
                  aria-label="Chat message input"
                  className="w-full bg-transparent resize-none text-[13px] min-h-[24px] max-h-[120px] py-1 pr-2 focus:outline-none placeholder:text-foreground-muted caret-foreground text-transparent selection:bg-brand-teal/30 leading-relaxed relative font-[inherit] tracking-[inherit]"
                  rows={1}
                  autoFocus
                />
                <MentionOverlay
                  text={input}
                  textareaRef={textareaRef}
                  slidePreviewUrls={slidePreviewUrls}
                />
              </div>

              {isLoading ? (
                <button
                  type="button"
                  onClick={handleStop}
                  title={composeInFlight ? "Force stop — partial report may be lost" : "Stop generation"}
                  className="flex-none w-7 h-7 rounded-lg flex items-center justify-center transition-all touch-target bg-white/10 hover:bg-white/20"
                  aria-label={composeInFlight ? "Force stop generation" : "Stop generation"}
                >
                  <Square className="h-3 w-3 fill-current" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim() && attachments.length === 0 && snippets.length === 0}
                  className="flex-none w-7 h-7 rounded-lg flex items-center justify-center transition-all touch-target"
                  style={{
                    background: (!input.trim() && attachments.length === 0 && snippets.length === 0) ? "transparent" : "var(--color-brand-teal)",
                    color: (!input.trim() && attachments.length === 0 && snippets.length === 0) ? "var(--foreground-muted)" : "var(--background)",
                  }}
                  aria-label="Send message"
                >
                  <Send className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    </FileDropZone>
  )
})
