// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatInput — Reusable chat input area with textarea, Send/Stop, PlusMenu, attachments.
 *
 * Extracted from ChatPanel.tsx. Handles:
 * - Textarea with auto-resize and IME-safe composition
 * - Send/Stop button toggle
 * - PlusMenu (file attach + snippet)
 * - AttachmentPreview + SnippetInput
 * - FileDropZone wrapper
 * - ⌘+Enter / Enter send preference
 *
 * Does NOT handle: @mentions, Options panel (deck-specific). Use `children` slot for those.
 */

"use client"

import { useRef, useState, useCallback, useEffect, forwardRef, useImperativeHandle, FormEvent, KeyboardEvent, ReactNode } from "react"
import { useCompositionSafe } from "@/hooks/useCompositionSafe"
import { useIsMobile } from "@/hooks/UseMobile"
import { uploadFile, validateFile, canAddMoreFiles, UploadedFile } from "@/services/uploadService"
import { PlusMenu } from "./PlusMenu"
import { AttachmentPreview, Attachment, SnippetAttachment } from "./AttachmentPreview"
import { FileDropZone } from "./FileDropZone"
import { SnippetInput } from "./SnippetInput"
import { Send, Square } from "lucide-react"
import { toast } from "sonner"

export interface ChatInputProps {
  /** Called with the final message text, uploaded files, snippets, and attachment metadata. */
  onSend: (text: string, uploadedFiles: UploadedFile[], snippets: { label: string; text: string }[], attachments: { fileName: string; fileType: string }[]) => void
  isLoading: boolean
  onStop: () => void
  disabled?: boolean
  placeholder?: string
  /** idToken for file upload. */
  idToken?: string
  /** Session ID for file upload context. */
  sessionId?: string
  /** Deck ID for file upload context. */
  deckId?: string
  /** Slot for additional UI above the textarea row (e.g., Options panel, @mentions overlay). */
  children?: ReactNode
  /** Stop button tooltip override. */
  stopTitle?: string
  /** Called on every input change (e.g., for @mention detection). */
  onInputChange?: (value: string) => void
  /** Overlay rendered inside the textarea's relative container (e.g., MentionOverlay). */
  textareaOverlay?: ReactNode
  /** Additional className for the textarea element (e.g., text-transparent for overlay mode). */
  textareaClassName?: string
}

export interface ChatInputHandle {
  insertAtCursor: (text: string) => void
  focus: () => void
  /** Ref to the internal textarea element (for MentionOverlay positioning). */
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  /** Programmatically add files (for external drop zones). */
  addFiles: (files: File[]) => void
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, isLoading, onStop, disabled, placeholder, idToken, sessionId, deckId, children, stopTitle, onInputChange, textareaOverlay, textareaClassName },
  ref,
) {
  const [input, setInput] = useState("")
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [snippetOpen, setSnippetOpen] = useState(false)
  const [snippets, setSnippets] = useState<SnippetAttachment[]>([])
  const [editingSnippetId, setEditingSnippetId] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { onCompositionStart, onCompositionEnd, getIsComposing } = useCompositionSafe()
  const isMobile = useIsMobile()

  const handleFilesRef = useRef<(files: FileList) => void>(() => {})

  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      const ta = textareaRef.current
      if (!ta) return
      const start = ta.selectionStart
      const end = ta.selectionEnd
      const before = input.slice(0, start)
      const after = input.slice(end)
      setInput(before + text + after)
      requestAnimationFrame(() => {
        ta.focus()
        const pos = start + text.length
        ta.setSelectionRange(pos, pos)
      })
    },
    focus() {
      textareaRef.current?.focus()
    },
    addFiles(files: File[]) {
      const fakeList = { length: files.length, item: (i: number) => files[i], [Symbol.iterator]: files[Symbol.iterator].bind(files) } as unknown as FileList
      handleFilesRef.current(fakeList)
    },
    textareaRef,
  }), [input])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (ta) {
      ta.style.height = "0px"
      ta.style.height = ta.scrollHeight + "px"
    }
  }, [input])

  const handleFiles = useCallback((files: FileList) => {
    const currentCount = attachments.length
    for (const file of Array.from(files)) {
      if (!canAddMoreFiles(currentCount + attachments.length)) {
        toast.error("Maximum 5 files can be attached at once.")
        break
      }
      const error = validateFile(file)
      if (error) { toast.error(error); continue }
      const id = crypto.randomUUID()
      setAttachments((prev) => [...prev, { id, file, status: "pending" }])
    }
  }, [attachments.length])
  useEffect(() => { handleFilesRef.current = handleFiles }, [handleFiles])

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const handleSnippetRequest = () => setSnippetOpen(true)

  const handleSnippetConfirm = (text: string) => {
    if (editingSnippetId) {
      setSnippets((prev) => prev.map((s) => s.id === editingSnippetId ? { ...s, text } : s))
      setEditingSnippetId(null)
    } else {
      setSnippets((prev) => [...prev, { id: crypto.randomUUID(), text }])
    }
  }

  const editSnippet = useCallback((id: string) => {
    setEditingSnippetId(id)
    setSnippetOpen(true)
  }, [])

  const removeSnippet = useCallback((id: string) => {
    setSnippets((prev) => prev.filter((s) => s.id !== id))
  }, [])

  const handleSend = async () => {
    if ((!input.trim() && attachments.length === 0 && snippets.length === 0) || isLoading || disabled) return

    // Upload pending attachments
    const uploadedFiles: UploadedFile[] = []
    for (const att of attachments) {
      if (att.status === "pending") {
        try {
          setAttachments((prev) => prev.map((a) => (a.id === att.id ? { ...a, status: "uploading" as const } : a)))
          const result = await uploadFile(att.file, idToken ?? "", sessionId ?? "", deckId !== "new" ? deckId : undefined)
          uploadedFiles.push(result)
          setAttachments((prev) => prev.map((a) => (a.id === att.id ? { ...a, status: "completed" as const, uploadId: result.uploadId } : a)))
        } catch {
          setAttachments((prev) => prev.map((a) => (a.id === att.id ? { ...a, status: "failed" as const, error: "Upload failed" } : a)))
        }
      }
    }

    const sentSnippets = snippets.map((s) => ({ label: "Text snippet", text: s.text }))
    const sentAttachments = uploadedFiles.map((f) => ({ fileName: f.fileName, fileType: f.fileType }))

    onSend(input, uploadedFiles, sentSnippets, sentAttachments)
    setInput("")
    setAttachments([])
    setSnippets([])
    requestAnimationFrame(() => textareaRef.current?.focus())
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    handleSend()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (getIsComposing(e)) return
    const canSendNow = input.trim() || attachments.length > 0 || snippets.length > 0
    const sendWithEnter = (() => { try { return JSON.parse(localStorage.getItem("sdpm-prefs") || "{}").sendWithEnter ?? false } catch { return false } })()

    if (sendWithEnter) {
      if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && canSendNow) {
        e.preventDefault()
        handleSend()
      }
    } else {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSendNow) {
        e.preventDefault()
        handleSend()
      }
    }
  }

  const canSend = input.trim() || attachments.length > 0 || snippets.length > 0

  return (
    <FileDropZone onFiles={handleFiles} onLongTextPaste={handleSnippetConfirm} pasteDisabled={snippetOpen} disabled={isLoading} className="relative">
      <SnippetInput
        open={snippetOpen}
        onClose={() => { setSnippetOpen(false); setEditingSnippetId(null) }}
        onConfirm={handleSnippetConfirm}
        initialText={editingSnippetId ? snippets.find((s) => s.id === editingSnippetId)?.text : undefined}
      />
      <div className="flex-none px-3 pb-6 pt-2 safe-bottom">
        <form onSubmit={handleSubmit} className="rounded-xl border border-white/[0.08] bg-background-raised search-glow">
          <AttachmentPreview
            attachments={attachments}
            snippets={snippets}
            onRemove={removeAttachment}
            onRemoveSnippet={removeSnippet}
            onEditSnippet={editSnippet}
          />

          {children}

          <div className="flex items-end gap-2 px-2 py-2">
            <PlusMenu
              onFilesSelected={handleFiles}
              onSnippetRequest={handleSnippetRequest}
              disabled={isLoading}
            />

            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => { setInput(e.target.value); onInputChange?.(e.target.value) }}
                onKeyDown={handleKeyDown}
                onCompositionStart={onCompositionStart}
                onCompositionEnd={onCompositionEnd}
                placeholder={placeholder ?? (isMobile ? "Ask anything…" : "Ask anything…  ⌘↵ send")}
                aria-label="Chat message input"
                className={`w-full bg-transparent resize-none text-sm min-h-[24px] max-h-[120px] py-1 pr-2 focus:outline-none placeholder:text-foreground-muted caret-foreground leading-relaxed font-[inherit] tracking-[inherit] ${textareaClassName ?? ""}`}
                rows={1}
                autoFocus
              />
              {textareaOverlay}
            </div>

            {isLoading ? (
              <button
                type="button"
                onClick={onStop}
                title={stopTitle ?? "Stop generation"}
                className="flex-none w-7 h-7 rounded-lg flex items-center justify-center transition-all touch-target bg-white/10 hover:bg-white/20"
                aria-label={stopTitle ?? "Stop generation"}
              >
                <Square className="h-3 w-3 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!canSend}
                className="flex-none w-7 h-7 rounded-lg flex items-center justify-center transition-all touch-target"
                style={{
                  background: !canSend ? "transparent" : "var(--color-brand-teal)",
                  color: !canSend ? "var(--foreground-muted)" : "var(--background)",
                }}
                aria-label="Send message"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </form>
      </div>
    </FileDropZone>
  )
})
