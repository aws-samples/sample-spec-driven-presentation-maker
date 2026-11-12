// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanel — Chat interface orchestrator.
 *
 * Delegates streaming to useChatStream, input to ChatInput.
 * Retains: history loading, resume after a reload or on a reopened deck, @mentions, Options,
 * side effects.
 */

"use client"

import { useEffect, useRef, useState, useImperativeHandle, forwardRef, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { IS_LOCAL } from "@/lib/mode"
import { loadRuntimeConfig } from "@/lib/runtimeConfig"
import { buildAttachedMarkers } from "@/lib/attachmentMarker"
import { generateSessionId, prepareAgentCore, setAgentConfig } from "@/services/agentCoreService"
import { deckSessionId, isOwnerPrefixed } from "@/lib/sessionId"
import { getChatHistory, patchDeck, type ChatMessage as ChatHistoryMessage } from "@/services/deckService"
import * as localService from "@/services/localService"
import type { UploadedFile } from "@/services/uploadService"
import { useChatStream, type Message, type ToolUseCallbackData } from "@/hooks/useChatStream"
import { useSlashPickerItems } from "@/hooks/useSlashPickerItems"
import { ChatInput, type ChatInputHandle } from "./ChatInput"
import { ChatMessage } from "./ChatMessage"
import { ComposerNoteCard } from "./ComposerNoteCard"
import { McpStatusBar } from "./McpStatusBar"
import { FileDropZone } from "./FileDropZone"
import { useIsMobile } from "@/hooks/UseMobile"
import { Send, ChevronRight, GitBranch } from "lucide-react"
import { ModeSelector } from "./ModeSelector"
import { HtmlFormatPill } from "./HtmlFormatPill"
import { SessionPickerDialog } from "./SessionPickerDialog"
import { ContinuedFromChip } from "./ContinuedFromChip"
import { EngineBadge } from "./EngineBadge"
import { ForkProgressCard } from "./ForkProgressCard"
import { LocalModelPicker } from "./LocalModelPicker"
import { usePreferences } from "@/hooks/usePreferences"
import { notifyError } from "@/lib/errors"
import { toast } from "sonner"
import { cutAtPrompt, cutLocalAtPrompt, isLocalHistoryFormat, parseLocalHistory, parseCloudHistory, settleStaleTasks } from "./chatHistory"
import { isResumable } from "@/lib/sessionState"
import { useLocale, useTranslations } from "next-intl"
import { forkKiroSession, listKiroSessions } from "@/services/kiroSessionsService"
import type { ForkSessionPhase, KiroSessionSummary, SessionOrigin } from "@/lib/local/kiro-sessions.types"
import { isLocalSessionNoticeCode, LOCAL_SESSION_NOTICE_KEYS } from "@/lib/local/sessionNotices"
import { useReview, type SubmittedReview } from "@/components/review/ReviewProvider"
import { ReviewDraftBar } from "@/components/review/ReviewDraftBar"
import { stripWhitespace } from "@/lib/review/schema"

interface ChatPanelProps {
  deckId: string
  chatSessionId?: string
  sessionOrigin?: SessionOrigin
  onDeckCreated?: (deckId: string) => void
  onPreviewInvalidated?: () => void
  onWorkflowPhase?: (phase: string) => void
  onLoadingChange?: (isLoading: boolean) => void
  /** The panel is on screen. A new deck's `prepare` waits until it is (Cloud). */
  visible?: boolean
}

/** Handle exposed to parents for input insertion and programmatic user messages. */
export interface ChatPanelHandle {
  insertAtCursor: (text: string) => void
  sendMessage: (text: string, options?: { displayContent?: string }) => Promise<void>
}

function formatRelativeTime(value: string, locale: string): string {
  const deltaSeconds = Math.round((new Date(value).getTime() - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" })
  if (Math.abs(deltaSeconds) < 60) return formatter.format(deltaSeconds, "second")
  const minutes = Math.round(deltaSeconds / 60)
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute")
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour")
  return formatter.format(Math.round(hours / 24), "day")
}

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel({ deckId, chatSessionId, sessionOrigin, onDeckCreated, onPreviewInvalidated, onWorkflowPhase, onLoadingChange, visible = true }, ref) {
  const t = useTranslations("chat")
  const tCompose = useTranslations("compose")
  const tSessionPicker = useTranslations("sessionPicker")
  const tReview = useTranslations("review")
  const locale = useLocale()
  const auth = useAuth()
  // --- Session ---
  // Cloud ids carry the owner prefix of the signed-in user (lib/sessionId.ts).
  const sub = auth.user?.profile?.sub
  const [sessionId, setSessionId] = useState(() => {
    if (chatSessionId) return chatSessionId
    if (deckId === "new") return generateSessionId(sub)
    return IS_LOCAL || !sub ? deckId.padEnd(36, "0") : deckSessionId(sub, deckId)
  })
  // A linked chat id of an earlier format whose history is empty is replaced for
  // this page load (see loadHistory); the prop-swap effect must not bring it back.
  const replacedLegacyIdRef = useRef<string | null>(null)
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId
  // Mid-stream guard: when a deck is created while the agent is still
  // streaming (init_deck_workspace in the import-pptx guide), the parent
  // re-renders with a fresh chatSessionId. Swapping sessionId here would
  // re-trigger history loading and clobber the in-flight messages
  // (toolUses disappear from the UI). Defer the swap until streaming
  // finishes, then apply it once isLoading flips back to false.
  const pendingChatSessionIdRef = useRef<string | null>(null)
  const isLoadingRef = useRef(false)
  useEffect(() => {
    if (chatSessionId && chatSessionId !== sessionId && chatSessionId !== replacedLegacyIdRef.current) {
      if (isLoadingRef.current) {
        pendingChatSessionIdRef.current = chatSessionId
      } else {
        setSessionId(chatSessionId)
      }
    }
    // After the swap chatSessionId === sessionId, so the re-run is a no-op.
  }, [chatSessionId, sessionId])

  // --- Config ---
  const [configLoaded, setConfigLoaded] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  // Set by the history load when the session may be working (Cloud: it was; Local: always, on a
  // deck); applied once the config is loaded.
  const [resumeCut, setResumeCut] = useState<{ cut: (prompt: string) => Message[] } | null>(null)

  // --- Options ---
  const [optionsOpen, setOptionsOpen] = useState(false)
  const { fetchWebImages, setFetchWebImages, agentMode, setAgentMode } = usePreferences()

  // --- Local kiro session continuation ---
  const [sessionPickerOpen, setSessionPickerOpen] = useState(false)
  const [recentSessions, setRecentSessions] = useState<KiroSessionSummary[]>([])
  const [forkingSession, setForkingSession] = useState<KiroSessionSummary | null>(null)
  const [forkProgress, setForkProgress] = useState<{ phase: ForkSessionPhase; replayed: number }>({ phase: "starting", replayed: 0 })
  const forkAbortControllerRef = useRef<AbortController | null>(null)
  const [forkError, setForkError] = useState(false)
  const [continuedOrigin, setContinuedOrigin] = useState<SessionOrigin | undefined>(sessionOrigin)

  useEffect(() => {
    setContinuedOrigin(sessionOrigin)
  }, [sessionOrigin])

  useEffect(() => {
    if (!IS_LOCAL || deckId !== "new") return
    const controller = new AbortController()
    listKiroSessions(false, controller.signal)
      .then((data) => setRecentSessions(data.recent.slice(0, 3)))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) setRecentSessions([])
      })
    return () => controller.abort()
  }, [deckId])

  useEffect(() => () => forkAbortControllerRef.current?.abort(), [])

  // --- Refs ---
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)
  const currentDeckId = useRef(deckId)
  currentDeckId.current = deckId

  const isMobile = useIsMobile()
  const slashPickerItems = useSlashPickerItems(auth.user?.id_token)
  // Mirror of the chat input; the HTML pill derives its state from the text alone.
  const [inputText, setInputText] = useState("")

  // --- Review comments (only the ChatPanel of the open deck shows and sends them) ---
  const review = useReview()
  const reviewActive = !!review?.enabled && review.deckId === deckId
  const hasReviewDrafts = reviewActive && (review?.readyDrafts.length ?? 0) > 0
  // Read in callbacks that outlive a render.
  const reviewRef = useRef(review)
  useEffect(() => { reviewRef.current = review })

  /** Persist chat messages to disk (Local mode only); `delivered`: the session whose stream ended before this save. */
  const saveLocalChat = useCallback((overrideDeckId?: string, delivered?: string) => {
    const did = overrideDeckId || currentDeckId.current
    if (!IS_LOCAL || !did) return
    localService.saveLocalChat(did, stream.messagesRef.current, delivered).catch((err) => notifyError(t("errorSaveHistory"), err))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- Tool event handler (side effects) ---
  const handleToolEvent = useCallback((toolName: string, toolUseData: ToolUseCallbackData | undefined) => {
    const idToken = auth.user?.id_token

    // Deck created
    if (toolUseData?.completed && toolUseData?.result?.deckId && onDeckCreated) {
      const resultDeckId = String(toolUseData.result.deckId)
      // intentional: best-effort — chat session linkage is a convenience; deck creation already succeeded
      if (idToken) patchDeck(resultDeckId, { chatSessionId: sessionIdRef.current }, idToken).catch((err) => console.error("patchDeck failed", err))
      onDeckCreated(resultDeckId)
      saveLocalChat(resultDeckId)
    }

    // Preview invalidated
    if (toolUseData?.completed && (toolName === "generate_pptx" || toolName.endsWith("_generate_pptx")) && onPreviewInvalidated) {
      onPreviewInvalidated()
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

    // Save after tool completed (also a background task's end: `taskEnd` comes as `completed`)
    if (toolUseData?.completed) setTimeout(() => saveLocalChat(), 100)

    // Save after tool started (ensures compose_slides is persisted; also a task's start, `taskStarted`)
    if (!toolUseData?.completed && !toolUseData?.stream) setTimeout(() => saveLocalChat(), 100)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, auth.user?.id_token, onDeckCreated, onPreviewInvalidated, onWorkflowPhase])

  // --- useChatStream ---
  // A send's or a replay's end, and a turn's end, save the chat once the render that holds their
  // messages is committed (saveLocalChat reads messagesRef, which follows the render): a replayed
  // period arrives in one chunk, so its messages are not rendered yet when its stream ends. The
  // save after a stream's end reports its session delivered: until then the server replays it.
  const [saveRequest, setSaveRequest] = useState(0)
  const deliveredRef = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!saveRequest) return
    const delivered = deliveredRef.current
    deliveredRef.current = undefined
    saveLocalChat(undefined, delivered)
  }, [saveRequest, saveLocalChat])
  const requestSave = useCallback((delivered?: string) => {
    if (!IS_LOCAL) return
    if (delivered) deliveredRef.current = delivered
    setSaveRequest((n) => n + 1)
  }, [])
  const mode = agentMode === "vibe" ? "vibe" : "spec"
  const stream = useChatStream({
    sessionId,
    mode,
    deckId: currentDeckId.current !== "new" ? currentDeckId.current : undefined,
    onToolEvent: handleToolEvent,
    onSendComplete: requestSave,
    onTurnEnd: requestSave,
  })

  const cancelFork = useCallback(() => {
    forkAbortControllerRef.current?.abort()
    forkAbortControllerRef.current = null
    setForkingSession(null)
    setForkProgress({ phase: "starting", replayed: 0 })
  }, [])

  const forkAndStart = useCallback(async (summary: KiroSessionSummary) => {
    forkAbortControllerRef.current?.abort()
    const controller = new AbortController()
    forkAbortControllerRef.current = controller
    setSessionPickerOpen(false)
    setForkError(false)
    setForkingSession(summary)
    setForkProgress({ phase: "starting", replayed: 0 })

    try {
      const result = await forkKiroSession({
        sourceSessionId: summary.sessionId,
        clientSessionId: sessionId,
      }, {
        signal: controller.signal,
        onPhase: (phase, detail) => setForkProgress({ phase, replayed: detail?.replayed ?? 0 }),
      })
      if (controller.signal.aborted) return

      forkAbortControllerRef.current = null
      sessionIdRef.current = result.sessionId
      setSessionId(result.sessionId)
      setContinuedOrigin(result.origin)
      setForkingSession(null)
      await stream.sendMessage("", undefined, undefined, undefined, {
        continuedFrom: result.origin,
        sessionIdOverride: result.sessionId,
        hideUserMessage: true,
        propagateError: true,
      })
    } catch (err) {
      if (controller.signal.aborted || (err instanceof Error && err.name === "AbortError")) {
        if (forkAbortControllerRef.current === controller) setForkingSession(null)
        return
      }
      console.error("Failed to continue from kiro session", err)
      const freshSessionId = generateSessionId(sub)
      sessionIdRef.current = freshSessionId
      setSessionId(freshSessionId)
      setContinuedOrigin(undefined)
      stream.setMessages([])
      setForkError(true)
      toast.error(tSessionPicker("forkFailed"))
    } finally {
      if (forkAbortControllerRef.current === controller) {
        forkAbortControllerRef.current = null
        setForkingSession(null)
      }
    }
  }, [sessionId, stream.sendMessage, stream.setMessages, tSessionPicker])

  // --- Ref handle ---
  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      chatInputRef.current?.insertAtCursor(text)
    },
    async sendMessage(text: string, options?: { displayContent?: string }) {
      await stream.sendMessage(text, undefined, undefined, undefined, options)
    },
  }), [stream.sendMessage])

  // --- Load agent config (cloud only) ---
  useEffect(() => {
    if (IS_LOCAL) { setConfigLoaded(true); return }
    async function loadConfig() {
      try {
        const config = await loadRuntimeConfig()
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
    // Local: a load the effect has re-run since (React's dev double run, a session id change)
    // sets nothing, so it cannot put the saved history over a replay the newer load started.
    let superseded = false
    async function loadHistory() {
      const idToken = auth.user?.id_token
      if (!IS_LOCAL && !idToken) return
      if (!sessionId) return
      setHistoryLoading(true)
      let raw: ChatHistoryMessage[] = []
      let loaded: ReturnType<typeof parseLocalHistory> = []
      try {
        const { messages: history, truncated } = await getChatHistory(sessionId, idToken ?? "", deckId || undefined)
        raw = history
        if (truncated) {
          toast.info(t("historyTruncated"))
        }
        if (history.length > 0) {
          // Local mode: .chat.json is already in ChatPanel's internal format
          if (IS_LOCAL && isLocalHistoryFormat(history)) {
            if (superseded) return
            loaded = parseLocalHistory(history)
            stream.setMessages(loaded)
          } else {
            const parsed = parseCloudHistory(history)
            if (parsed.length > 0) stream.setMessages(parsed)
          }
        } else if (!IS_LOCAL && sub && deckId && deckId !== "new" && !isOwnerPrefixed(sessionId)) {
          // An earlier-format id with no history: continue under this user's own id.
          replacedLegacyIdRef.current = sessionId
          setSessionId(deckSessionId(sub, deckId))
        }
      } finally {
        setHistoryLoading(false)
      }
      // The session may be working (reload, wake, reopened deck): follow it once the agent
      // config is loaded. The replay rebuilds the work from its opening prompt on. Cloud: when
      // it was working as this page last saw it. Local: always (the server also replays a
      // period that ended before a page saved it).
      if (IS_LOCAL && deckId && deckId !== "new") {
        if (superseded) return
        setResumeCut({ cut: (prompt: string) => cutLocalAtPrompt(loaded, prompt) })
      } else if (!IS_LOCAL && deckId && deckId !== "new" && isResumable(sessionId)) {
        setResumeCut({ cut: (prompt: string) => parseCloudHistory(cutAtPrompt(raw, prompt)) })
      }
    }
    if (auth.isAuthenticated) loadHistory()
    return () => { superseded = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, auth.isAuthenticated])

  // --- Resume a working session ---
  useEffect(() => {
    if (!resumeCut || !configLoaded) return
    setResumeCut(null)
    const resumedId = sessionId
    void stream.resume(resumeCut.cut).then((working) => {
      // Nothing runs: a task the history shows running was stopped with its work.
      if (working === false && sessionIdRef.current === resumedId) stream.setMessages(settleStaleTasks)
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeCut, configLoaded])

  // --- Prepare the new deck's session (Cloud) ---
  // Once per mount, when the new deck screen is first shown (the shell keeps this panel
  // mounted while the chat is closed or another tab is shown), no re-warm: the first prompt
  // then finds its MCP connections built.
  const preparedRef = useRef(false)
  useEffect(() => {
    if (IS_LOCAL || deckId !== "new" || !visible || !configLoaded || preparedRef.current) return
    const token = auth.user?.access_token
    if (!token) return
    preparedRef.current = true
    // intentional: best-effort — without it the first prompt builds the session itself
    prepareAgentCore(sessionIdRef.current, token, mode).catch((err: unknown) => console.warn("Prepare failed:", err))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deckId, visible, configLoaded, auth.user?.access_token])

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
  ): Promise<boolean> => {
    if (!configLoaded) return Promise.resolve(false)

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

    return stream.sendMessage(fullMessage, uploadedFiles, snippets, attachments, { displayContent: text })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configLoaded, deckId, fetchWebImages, stream.sendMessage])

  /**
   * Send from the input. With comments waiting, the server first writes the review file and
   * returns the chat message (the typed text as `note`, comments, file path, instructions,
   * `[review:<id>]`), which is sent as-is and also shown (Local .chat.json keeps the display
   * text). A failed write keeps the comments and the typed text (`false` keeps the input). A
   * failed send puts the frames back into the drafts and the text back into an empty input, so the
   * request can be sent again (the chat shows the error).
   */
  const handleInputSend = useCallback(async (
    text: string,
    uploadedFiles: UploadedFile[],
    snippets: { label: string; text: string }[],
    attachments: { fileName: string; fileType: string }[],
  ): Promise<void | false> => {
    if (!configLoaded) return false
    const r = reviewRef.current
    if (!hasReviewDrafts || !r) {
      // Agent working: a steer. A steer that was not accepted keeps the input.
      if (stream.isLoading) return (await handleSend(text, uploadedFiles, snippets, attachments)) ? undefined : false
      handleSend(text, uploadedFiles, snippets, attachments)
      return
    }
    let created: SubmittedReview
    try {
      created = await r.submit(text)
    } catch (err) {
      notifyError(tReview("sendFailed"), err)
      return false
    }
    void handleSend(created.message, uploadedFiles, snippets, attachments).then((ok) => {
      if (ok) return
      created.restore()
      // Later than ChatInput clearing the input after this send.
      setTimeout(() => {
        const input = chatInputRef.current
        if (text.trim() && input && !input.textareaRef.current?.value.trim()) input.replaceText(text)
      }, 100)
    })
  }, [configLoaded, hasReviewDrafts, handleSend, tReview, stream.isLoading])

  const isLoading = stream.isLoading || forkingSession !== null
  // A send while the agent works is a steer. Local: only into this panel's own invoke or the
  // period it follows (not a fork that is starting).
  const canSendWhileLoading = !IS_LOCAL || (stream.isLoading && forkingSession === null)

  // Sync streaming flag and flush any deferred sessionId swap once
  // streaming finishes — at that point loadHistory can safely re-fetch
  // (the .chat.json server-side state is already complete).
  // Uses the combined isLoading (not stream.isLoading alone): a fork that
  // is starting is also in flight.
  useEffect(() => {
    isLoadingRef.current = isLoading
    onLoadingChange?.(isLoading)
    if (!isLoading && pendingChatSessionIdRef.current) {
      const next = pendingChatSessionIdRef.current
      pendingChatSessionIdRef.current = null
      setSessionId(next)
    }
    return () => onLoadingChange?.(false)
  }, [isLoading, onLoadingChange])

  const isInitial = stream.messages.length === 0 && !historyLoading
  // Only the initial screen shows the pill, so only it keeps the text: a long chat skips the
  // per-keystroke re-render (the draft bar's blank flag only re-renders when it flips).
  const [inputBlank, setInputBlank] = useState(true)
  const handleInputChange = useCallback((value: string) => {
    if (isInitial) setInputText(value)
    setInputBlank(!stripWhitespace(value))
  }, [isInitial])

  return (
    <>
      <FileDropZone onFiles={(files) => chatInputRef.current?.addFiles(Array.from(files))} disabled={isLoading && !canSendWhileLoading} className="flex flex-col h-full">
      {continuedOrigin && (
        <div className="flex-none px-4 pt-3">
          <ContinuedFromChip origin={continuedOrigin} />
        </div>
      )}
      {/* Messages area */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-4 py-4" role="log" aria-label={t("chatMessages")}
        onScroll={() => {
          const el = scrollContainerRef.current
          if (!el) return
          shouldAutoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
      >
        {forkingSession ? (
          <ForkProgressCard
            session={forkingSession}
            phase={forkProgress.phase}
            replayed={forkProgress.replayed}
            onCancel={cancelFork}
          />
        ) : historyLoading ? (
          <div className="space-y-4 animate-pulse">
            {[0.6, 1, 0.75].map((w, i) => (
              <div key={i} className={i % 2 === 0 ? "flex justify-end" : "flex gap-2.5"}>
                {i % 2 !== 0 && <div className="w-6 h-6 rounded-full bg-foreground/[0.06] flex-none" />}
                <div className="rounded-2xl bg-foreground/[0.04] h-10" style={{ width: `${w * 70}%` }} />
              </div>
            ))}
          </div>
        ) : isInitial ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <div className="w-12 h-12 rounded-2xl flex items-center justify-center bg-brand-teal-soft mb-5">
              <Send className="h-5 w-5 text-brand-teal" />
            </div>
            <h2 className="text-xl font-bold tracking-[-0.03em] text-foreground mb-1">{t("letsPresent")}</h2>
            <p className="text-sm text-foreground-muted leading-relaxed mb-6">
              {t("emptyHint")}
            </p>
            {IS_LOCAL && recentSessions.length > 0 && (
              <section className="mb-6 w-full max-w-xs text-left" aria-labelledby="recent-kiro-sessions-heading">
                <div className="mb-2 flex items-baseline justify-between gap-2">
                  <h3 id="recent-kiro-sessions-heading" className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">
                    {tCompose("recentSessionsHeading")}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setSessionPickerOpen(true)}
                    className="-mr-2 min-h-11 rounded-lg px-2 text-xs font-medium text-brand-teal motion-safe:transition-colors hover:bg-brand-teal-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                  >
                    {tCompose("pickOtherSession")}
                  </button>
                </div>
                <div className="space-y-1.5">
                  {recentSessions.map((recent) => (
                    <button
                      key={recent.sessionId}
                      type="button"
                      onClick={() => void forkAndStart(recent)}
                      className="flex min-h-14 w-full items-center gap-2.5 rounded-xl border border-border px-3 py-2 text-left motion-safe:transition-colors hover:border-border-hover hover:bg-background-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                    >
                      <GitBranch className="h-4 w-4 flex-none text-brand-teal" aria-hidden="true" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-foreground">{recent.title}</span>
                        <span className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-foreground-muted">
                          <span className="truncate">{recent.project} · {formatRelativeTime(recent.updatedAt, locale)}</span>
                          <EngineBadge engine={recent.engine} />
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            )}
            {forkError && (
              <p role="alert" className="mb-4 text-sm text-red-600 dark:text-red-400">
                {tSessionPicker("forkFailed")}
              </p>
            )}
            {/* Example prompts are a hint for a blank slate; recent sessions are a stronger one, so show only one of the two. */}
            {!(IS_LOCAL && recentSessions.length > 0) && (
              <div className="flex flex-col gap-2 w-full max-w-xs mb-8">
                {[t("example1"), t("example2"), t("example3")].map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => chatInputRef.current?.insertAtCursor(example)}
                    className="text-left text-sm text-foreground-muted px-3.5 py-2.5 rounded-xl border border-border hover:border-border-hover hover:text-foreground transition-colors"
                  >
                    {example}
                  </button>
                ))}
              </div>
            )}
            <ModeSelector value={agentMode} onChange={setAgentMode} />
            <HtmlFormatPill text={inputText} onChange={(next) => chatInputRef.current?.replaceText(next)} />
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
                {IS_LOCAL && isLocalSessionNoticeCode(msg.localNotice) && (
                  <p role="status" className="mb-2 ml-10 text-xs text-foreground-muted">
                    {t(LOCAL_SESSION_NOTICE_KEYS[msg.localNotice])}
                  </p>
                )}
                {msg.composerNote ? (
                  <div className="ml-8.5">
                    <ComposerNoteCard direction="from" {...msg.composerNote} />
                  </div>
                ) : (
                <ChatMessage
                  role={msg.role}
                  content={msg.content}
                  toolUses={msg.toolUses}
                  blocks={msg.blocks}
                  snippets={msg.snippets}
                  attachments={msg.attachments}
                  isStreaming={stream.turnActive && i === stream.messages.length - 1}
                  sessionWorking={stream.isLoading}
                  idToken={auth.user?.id_token}
                  onSend={(text: string) => handleSend(text, [], [], [])}
                  hearingDisabled={i < lastUserIdx}
                  deckId={deckId}
                />
                )}
                {msg.steerNotDelivered ? (
                  <p className="mt-1 text-right text-xs text-foreground-muted">{t("steerNotDelivered")}</p>
                ) : msg.steerState && (
                  <p className="mt-1 text-right text-xs text-foreground-muted">
                    {msg.steerState === "delivered" ? t("steerDelivered") : t("steerPending")}
                  </p>
                )}
              </div>
            ))
            })()}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {(stream.stopping || stream.reconnecting) ? (
        <p role="status" className="flex-none px-4 pb-1 text-xs text-foreground-muted">
          {stream.stopping ? t("stopping") : t("reconnecting")}
        </p>
      ) : stream.isLoading && !stream.turnActive
          && stream.messages.some((m) => m.toolUses.some((tool) => tool.task?.state === "running")) && (
        <p role="status" className="flex-none px-4 pb-1 text-xs text-foreground-muted">
          {t("backgroundWorking")}
        </p>
      )}

      {/* Input area */}
      <ChatInput
          ref={chatInputRef}
          onSend={handleInputSend}
          isLoading={isLoading}
          onStop={stream.stopGeneration}
          canSendWhileLoading={canSendWhileLoading}
          disabled={!configLoaded}
          placeholder={isMobile ? t("placeholderMobile") : t("placeholderDesktop")}
          topSlot={reviewActive ? <ReviewDraftBar inputBlank={inputBlank} /> : undefined}
          sendOverride={hasReviewDrafts && review ? { label: tReview("send"), blocked: isLoading && !canSendWhileLoading, canSend: review.canSubmit } : undefined}
          idToken={auth.user?.id_token}
          sessionId={sessionId}
          deckId={deckId}
          onContinueFromSession={() => setSessionPickerOpen(true)}
          continueFromSessionDisabled={deckId !== "new" || stream.messages.length > 0}
          slashItems={slashPickerItems.items}
          slashLoading={slashPickerItems.loading}
          onSlashOpen={slashPickerItems.ensure}
          onTextareaFocus={slashPickerItems.ensure}
          onInputChange={handleInputChange}
        >
          {/* Local: this chat's kiro-cli model and effort */}
          {IS_LOCAL && (
            <div className="px-2 pt-1">
              <LocalModelPicker
                sessionId={sessionId}
                isNewChat={deckId === "new" && stream.messages.length === 0}
                busy={isLoading}
                disabled={forkingSession !== null}
              />
            </div>
          )}
          {/* Options expander — the only option (web images) is cloud-only */}
          {!IS_LOCAL && (
          <div className="px-2">
            <button
              type="button"
              onClick={() => setOptionsOpen((v) => !v)}
              className="flex items-center gap-1 text-[11px] text-foreground-muted hover:text-foreground transition-colors py-1"
            >
              <ChevronRight className={`h-3 w-3 transition-transform duration-200 ${optionsOpen ? "rotate-90" : ""}`} />
              {t("options")}
            </button>
            {optionsOpen && (
              <div className="flex flex-col gap-2 pb-2 pl-1">
                <label className="group flex items-center justify-between gap-3 rounded-lg px-3 py-2 cursor-pointer
                  bg-foreground/[0.02] hover:bg-foreground/[0.05] transition-colors">
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="text-xs text-foreground-secondary font-medium select-none">{t("fetchWebImages")}</span>
                    <span className="text-xs text-foreground-muted select-none leading-snug">{t("fetchWebImagesDescription")}</span>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={fetchWebImages}
                    onClick={() => setFetchWebImages(!fetchWebImages)}
                    className={`relative flex-none w-9 h-5 rounded-full transition-colors duration-200 ${
                      fetchWebImages ? "bg-brand-teal" : "bg-foreground/[0.1]"
                    }`}
                  >
                    <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                      fetchWebImages ? "translate-x-4" : ""
                    }`} />
                  </button>
                </label>
              </div>
            )}
          </div>
          )}
        </ChatInput>
      </FileDropZone>
      {IS_LOCAL && (
        <SessionPickerDialog
          open={sessionPickerOpen}
          onOpenChange={setSessionPickerOpen}
          onSelect={(summary) => void forkAndStart(summary)}
        />
      )}
    </>
  )
})
