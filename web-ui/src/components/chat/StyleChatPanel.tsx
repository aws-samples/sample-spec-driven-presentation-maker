// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatPanel — Chat panel for style creation/editing.
 *
 * Uses useChatStream + ChatInput (shared components).
 * No @mentions, no Options, no Panel A/B, no reconnect.
 * Extracts style_html from tool results to update live preview.
 */

"use client"

import { useEffect, useRef, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { useChatStream, type ToolUseCallbackData } from "@/hooks/useChatStream"
import { ChatInput, type ChatInputHandle } from "./ChatInput"
import { ChatMessage } from "./ChatMessage"
import { generateSessionId } from "@/services/agentCoreService"
import { IS_LOCAL } from "@/lib/mode"
import { Send } from "lucide-react"
import type { UploadedFile } from "@/services/uploadService"

interface StyleChatPanelProps {
  styleId: string
  /** Called when agent writes style.html — passes HTML content for live preview. */
  onStyleHtmlUpdate?: (html: string) => void
  /** Called when agent saves the style (run_style_python save=True succeeded). */
  onStyleSaved?: (saved: { title: string; filename: string }) => void
}

export function StyleChatPanel({ styleId, onStyleHtmlUpdate, onStyleSaved }: StyleChatPanelProps) {
  const auth = useAuth()
  const sessionId = useRef(generateSessionId()).current
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)

  const handleToolEvent = useCallback((toolName: string, data: ToolUseCallbackData | undefined) => {
    if (data?.completed && data?.result && onStyleHtmlUpdate) {
      const result = data.result as Record<string, unknown>
      if (typeof result.style_html === "string") {
        onStyleHtmlUpdate(result.style_html)
      }
      if (result.saved && onStyleSaved) {
        const saved = result.saved as { title: string; filename: string }
        onStyleSaved(saved)
      }
    }
  }, [onStyleHtmlUpdate, onStyleSaved])

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

  const handleSend = useCallback(async (
    text: string,
    uploadedFiles: UploadedFile[],
    snippets: { label: string; text: string }[],
    attachments: { fileName: string; fileType: string }[],
  ) => {
    let fullMessage = text
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
  }, [stream.sendMessage])

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
              <Send className="h-5 w-5 text-brand-teal" />
            </div>
            <h2 className="text-[22px] font-bold tracking-[-0.03em] text-brand-teal mb-1">Style Creator</h2>
            <p className="text-sm text-foreground-muted leading-relaxed">
              Describe the style you want, or drop a reference file
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {stream.messages.map((msg, i) => (
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
              />
            ))}
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
