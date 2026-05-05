// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatPanel — Chat panel for style creation/editing.
 *
 * Uses useChatStream + ChatInput (shared components).
 * No @mentions, no Options, no Panel A/B, no reconnect.
 * Detects write_style calls and notifies parent to refresh preview.
 */

"use client"

import { useEffect, useRef, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { useChatStream, type ToolUseCallbackData } from "@/hooks/useChatStream"
import { ChatInput, type ChatInputHandle } from "./ChatInput"
import { ChatMessage } from "./ChatMessage"
import { generateSessionId } from "@/services/agentCoreService"
import { IS_LOCAL } from "@/lib/mode"
import { Sparkles } from "lucide-react"
import type { UploadedFile } from "@/services/uploadService"

interface StyleChatPanelProps {
  styleId: string
  /** Called when agent writes a style — parent should refetch preview. */
  onStyleWritten?: () => void
  /** Called when agent saves the style (write_style succeeded with saved result). */
  onStyleSaved?: (saved: { title: string; filename: string }) => void
}

export function StyleChatPanel({ styleId, onStyleWritten, onStyleSaved }: StyleChatPanelProps) {
  const auth = useAuth()
  const sessionId = useRef(generateSessionId()).current
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)

  const handleToolEvent = useCallback((toolName: string, data: ToolUseCallbackData | undefined) => {
    if (data?.completed && data?.result) {
      const result = data.result as Record<string, unknown>
      if (result.saved) {
        const saved = result.saved as { title: string; filename: string }
        onStyleWritten?.()
        onStyleSaved?.(saved)
      }
    }
  }, [onStyleWritten, onStyleSaved])

  const stream = useChatStream({
    sessionId,
    mode: "style",
    onToolEvent: handleToolEvent,
    onSendComplete: undefined,
  })

  // Save chat after each send (Local mode)
  useEffect(() => {
    if (!stream.isLoading && stream.messages.length > 0 && IS_LOCAL && styleId) {
      fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deckId: styleId, messages: stream.messages }),
      }).catch(() => {})
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

  const handleSend = useCallback(async (
    text: string,
    uploadedFiles: UploadedFile[],
    snippets: { label: string; text: string }[],
    attachments: { fileName: string; fileType: string }[],
  ) => {
    let fullMessage = text
    // First message: inject style context so the agent knows which style to write
    if (!hasSentRef.current) {
      hasSentRef.current = true
      fullMessage = `[Style: ${styleId}]\n\n${fullMessage}`
    }
    if (uploadedFiles.length > 0) {
      const fileInfo = uploadedFiles.map((f) => `[Attached: ${f.fileName} (uploadId: ${f.uploadId})]`).join("\n")
      fullMessage = `${fileInfo}\n\n${fullMessage}`
    }
    if (snippets.length > 0) {
      const snippetInfo = snippets.map((s) => `---snippet---\n${s.text}\n---/snippet---`).join("\n\n")
      fullMessage = `${fullMessage}\n\n${snippetInfo}`
    }
    await stream.sendMessage(fullMessage, uploadedFiles, snippets, attachments)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.sendMessage, styleId])

  const isInitial = stream.messages.length === 0

  return (
    <div className="flex flex-col h-full">
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto px-4 py-4"
        role="log"
        aria-label="Style chat messages"
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
            <h2 className="text-[22px] font-bold tracking-[-0.03em] text-brand-teal mb-1">Style Creator</h2>
            <p className="text-sm text-foreground-muted leading-relaxed mb-6">
              Describe the style you want, or drop a reference file
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {["Dark minimal with gradients", "Corporate blue with charts", "Like Apple keynotes"].map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => { chatInputRef.current?.insertAtCursor(chip); chatInputRef.current?.focus() }}
                  className="px-3 py-1.5 rounded-full text-xs text-foreground-muted hover:text-foreground border border-white/[0.08] hover:border-white/[0.15] hover:bg-white/[0.04] transition-colors"
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {(() => {
              const lastUserIdx = stream.messages.findLastIndex((m) => m.role === "user")
              return stream.messages.map((msg, i) => (
              <ChatMessage
                key={i}
                role={msg.role}
                content={msg.content}
                toolUses={msg.toolUses}
                blocks={msg.blocks}
                snippets={msg.snippets}
                attachments={msg.attachments}
                isStreaming={stream.isLoading && i === stream.messages.length - 1}
                idToken={auth.user?.id_token}
                accessToken={auth.user?.access_token}
                sessionId={sessionId}
                onSend={(text: string) => handleSend(text, [], [], [])}
                hearingDisabled={i < lastUserIdx}
              />
            ))
            })()}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <ChatInput
        ref={chatInputRef}
        onSend={handleSend}
        isLoading={stream.isLoading}
        onStop={stream.stopGeneration}
        idToken={auth.user?.id_token}
        sessionId={sessionId}
        placeholder="Describe your style…  ⌘↵ send"
      />
    </div>
  )
}
