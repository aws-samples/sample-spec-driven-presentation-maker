// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatPanel — Chat panel for style creation/editing.
 *
 * Uses useChatStream + ChatInput (shared components).
 * No @mentions, no Options, no Panel A/B, no reconnect.
 * Detects write_style calls and notifies parent to refresh preview.
 *
 * Comments (inside the style page's enabled ReviewProvider): the frames drawn on the style
 * preview collect in a draft bar above the input, and one send turns them and the typed text
 * into a change request message (`createRequest` of the provider), sent like any message.
 * A steer the agent did not take puts the frames back into the drafts and the text back into
 * an empty input. Steers the agent has not read yet wait as cards above the input (SteerQueue).
 */

"use client"

import { useEffect, useRef, useCallback, useState } from "react"
import { useTranslations } from "next-intl"
import { useAuth } from "@/hooks/useAuth"
import { useChatStream, type SendMessageOptions, type ToolUseCallbackData } from "@/hooks/useChatStream"
import { ChatInput, type ChatInputHandle } from "./ChatInput"
import { ChatMessage } from "./ChatMessage"
import { SteerQueue } from "./SteerQueue"
import { FileDropZone } from "./FileDropZone"
import { generateSessionId, setAgentConfig } from "@/services/agentCoreService"
import { IS_LOCAL } from "@/lib/mode"
import { loadRuntimeConfig } from "@/lib/runtimeConfig"
import { saveLocalChat } from "@/services/localService"
import { Sparkles, MessageSquare, Image, Palette } from "lucide-react"
import type { UploadedFile } from "@/services/uploadService"
import { buildAttachedMarkers } from "@/lib/attachmentMarker"
import { notifyError } from "@/lib/errors"
import { useReview, type SubmittedReview } from "@/components/review/ReviewProvider"
import { ReviewDraftBar } from "@/components/review/ReviewDraftBar"
import { stripWhitespace } from "@/lib/review/schema"

interface StyleChatPanelProps {
  /** Style the chat edits; "" for a new style, which the agent names. */
  styleId: string
  /** Called when agent writes a style — parent should refetch preview. */
  onStyleWritten?: () => void
  /** Called when agent saves the style (write_style succeeded with saved result). */
  onStyleSaved?: (saved: { title?: string; filename: string }) => void
  /** Reports whether the agent is working (the comment tool shows its busy hint). */
  onLoadingChange?: (loading: boolean) => void
}

export function StyleChatPanel({ styleId, onStyleWritten, onStyleSaved, onLoadingChange }: StyleChatPanelProps) {
  const t = useTranslations("styleChat")
  const tChat = useTranslations("chat")
  const tReview = useTranslations("review")
  const auth = useAuth()
  const sessionId = useRef(generateSessionId(auth.user?.profile?.sub)).current
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)

  const handleToolEvent = useCallback((toolName: string, data: ToolUseCallbackData | undefined) => {
    if (data?.completed && data?.result) {
      const result = data.result as Record<string, unknown>
      if (result.saved) {
        const saved = result.saved as { title?: string; filename: string }
        onStyleWritten?.()
        onStyleSaved?.(saved)
      }
    }
  }, [onStyleWritten, onStyleSaved])

  const stream = useChatStream({
    sessionId,
    mode: "style_creator",
    onToolEvent: handleToolEvent,
    onSendComplete: undefined,
  })

  // Load agent config (cloud only)
  const [configLoaded, setConfigLoaded] = useState(IS_LOCAL)
  useEffect(() => {
    if (IS_LOCAL) return
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

  // Save chat after each send (Local mode)
  useEffect(() => {
    if (!stream.isLoading && stream.messages.length > 0 && IS_LOCAL && styleId) {
      saveLocalChat(styleId, stream.messages).catch((err) => notifyError(t("saveChatFailed"), err))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.isLoading])

  // Auto-scroll
  useEffect(() => {
    if (shouldAutoScroll.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [stream.messages])

  const hasSentRef = useRef(false)

  const handleSend = useCallback((
    text: string,
    uploadedFiles: UploadedFile[],
    snippets: { label: string; text: string }[],
    attachments: { fileName: string; fileType: string }[],
    steer?: Pick<SendMessageOptions, "inputText" | "onSteerFailed">,
  ): void => {
    let fullMessage = text
    // First message on an existing style: name it so the agent writes that style.
    // A new style (no styleId yet) is named by the agent; the parent follows its first save.
    if (!hasSentRef.current) {
      hasSentRef.current = true
      if (styleId) fullMessage = `[Style: ${styleId}]\n\n${fullMessage}`
    }
    if (uploadedFiles.length > 0) {
      fullMessage = `${buildAttachedMarkers(uploadedFiles)}\n\n${fullMessage}`
    }
    if (snippets.length > 0) {
      const snippetInfo = snippets.map((s) => `---snippet---\n${s.text}\n---/snippet---`).join("\n\n")
      fullMessage = `${fullMessage}\n\n${snippetInfo}`
    }
    // Returns at once (sendMessage settles only when the turn ends), so ChatInput clears the
    // input; a steer that could not be sent calls `onSteerFailed`.
    void stream.sendMessage(fullMessage, uploadedFiles, snippets, attachments, steer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.sendMessage, styleId])

  /**
   * Put a steer's text back into the input: after the text there, when it has some. Later than
   * ChatInput clearing the input after the send it came from.
   */
  const putBackIntoInput = useCallback((text: string) => {
    setTimeout(() => {
      const input = chatInputRef.current
      if (!input || !text.trim()) return
      const current = input.textareaRef.current?.value ?? ""
      input.replaceText(current.trim() ? `${current.trimEnd()}\n\n${text}` : text)
    }, 0)
  }, [])

  useEffect(() => {
    onLoadingChange?.(stream.isLoading)
    return () => onLoadingChange?.(false)
  }, [stream.isLoading, onLoadingChange])

  // --- Review comments from the style preview ---
  const review = useReview()
  const reviewActive = !!review?.enabled
  const hasReviewDrafts = reviewActive && (review?.readyDrafts.length ?? 0) > 0
  // Read in callbacks that outlive a render.
  const reviewRef = useRef(review)
  useEffect(() => { reviewRef.current = review })
  const [inputBlank, setInputBlank] = useState(true)
  const handleInputChange = useCallback((value: string) => setInputBlank(!stripWhitespace(value)), [])

  /**
   * Send from the input. A plain send goes straight to `handleSend` (not wrapped in a
   * promise, so the input clears at once; a steer that could not be sent puts its text back).
   * With comments waiting, the typed text becomes the request's note and the request message is
   * sent instead.
   */
  const handleInputSend = useCallback((
    text: string,
    uploadedFiles: UploadedFile[],
    snippets: { label: string; text: string }[],
    attachments: { fileName: string; fileType: string }[],
  ) => {
    const r = reviewRef.current
    if (!hasReviewDrafts || !r) {
      return handleSend(text, uploadedFiles, snippets, attachments, { inputText: text, onSteerFailed: () => putBackIntoInput(text) })
    }
    return (async (): Promise<void | false> => {
      let created: SubmittedReview
      try {
        created = await r.submit(text)
      } catch (err) {
        notifyError(tReview("sendFailed"), err)
        return false
      }
      handleSend(created.message, uploadedFiles, snippets, attachments, {
        inputText: text,
        onSteerFailed: () => {
          created.restore()
          putBackIntoInput(text)
        },
      })
    })()
  }, [hasReviewDrafts, handleSend, putBackIntoInput, tReview])

  const isInitial = stream.messages.length === 0

  return (
    <FileDropZone onFiles={(files) => chatInputRef.current?.addFiles(Array.from(files))} className="flex flex-col h-full">
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto px-4 py-4"
        role="log"
        aria-label={t("chatMessagesAria")}
        onScroll={() => {
          const el = scrollContainerRef.current
          if (!el) return
          shouldAutoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
      >
        {isInitial ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <div className="w-12 h-12 rounded-2xl flex items-center justify-center bg-brand-teal-soft mb-5">
              <Sparkles className="h-5 w-5 text-brand-teal" />
            </div>
            <h2 className="text-xl font-bold tracking-[-0.03em] text-foreground mb-3">{t("styleCreator")}</h2>
            <div className="flex flex-col gap-2 text-sm text-foreground-muted">
              <div className="flex items-center gap-2.5">
                <MessageSquare className="h-4 w-4 text-brand-teal/70 shrink-0" />
                <span>{t("describeVision")}</span>
              </div>
              <div className="flex items-center gap-2.5">
                <Image className="h-4 w-4 text-brand-teal/70 shrink-0" />
                <span>{t("dropReference")}</span>
              </div>
              <div className="flex items-center gap-2.5">
                <Palette className="h-4 w-4 text-brand-teal/70 shrink-0" />
                <span>{t("customizeExisting")}</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {(() => {
              const lastUserIdx = stream.messages.findLastIndex((m) => m.role === "user")
              return stream.messages.map((msg, i) => (
              <div key={i}>
                <ChatMessage
                  role={msg.role}
                  content={msg.content}
                  toolUses={msg.toolUses}
                  blocks={msg.blocks}
                  snippets={msg.snippets}
                  attachments={msg.attachments}
                  isStreaming={stream.isLoading && i === stream.messages.length - 1}
                  idToken={auth.user?.id_token}
                  onSend={(text: string) => handleSend(text, [], [], [])}
                  hearingDisabled={i < lastUserIdx}
                  arrived={!!msg.steerId && stream.arrivedSteerIds.has(msg.steerId)}
                />
              </div>
            ))
            })()}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {(stream.stopping || stream.reconnecting) && (
        <p role="status" className="flex-none px-4 pb-1 text-xs text-foreground-muted">
          {stream.stopping ? tChat("stopping") : tChat("reconnecting")}
        </p>
      )}

      <SteerQueue
        steers={stream.steerQueue}
        onBackToInput={(steer, text) => {
          stream.dismissSteer(steer.id)
          putBackIntoInput(text)
        }}
        onDismiss={stream.dismissSteer}
      />

      <ChatInput
        ref={chatInputRef}
        onSend={handleInputSend}
        onInputChange={handleInputChange}
        topSlot={reviewActive ? <ReviewDraftBar inputBlank={inputBlank} /> : undefined}
        sendOverride={hasReviewDrafts && review ? { label: tReview("send"), blocked: false, canSend: review.canSubmit } : undefined}
        isLoading={stream.isLoading}
        onStop={stream.stopGeneration}
        canSendWhileLoading
        idToken={auth.user?.id_token}
        sessionId={sessionId}
        placeholder={t("placeholder")}
      />
    </FileDropZone>
  )
}
