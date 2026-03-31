// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SnippetInput — Dialog for entering a text snippet to attach to a message.
 */

"use client"

import { useState, useRef, useEffect } from "react"

interface SnippetInputProps {
  /** Whether the dialog is open. */
  open: boolean
  /** Called when dialog closes. */
  onClose: () => void
  /** Called with the snippet text when confirmed. */
  onConfirm: (text: string) => void
  /** Initial text for editing an existing snippet. */
  initialText?: string
}

/**
 * Modal dialog with a textarea for pasting/typing a text snippet.
 *
 * @param props - SnippetInputProps
 */
export function SnippetInput({ open, onClose, onConfirm, initialText }: SnippetInputProps) {
  const [text, setText] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (open) {
      setText(initialText || "")
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }, [open, initialText])

  if (!open) return null

  const handleConfirm = () => {
    if (text.trim()) {
      onConfirm(text)
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-popover border border-border rounded-xl shadow-xl w-full max-w-lg mx-4 p-4">
        <h3 className="text-sm font-medium mb-2">Text Snippet</h3>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste or type your text here…"
          className="w-full h-48 bg-muted/50 border border-border/40 rounded-lg p-3 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <div className="flex justify-between items-center mt-3">
          <span className="text-xs text-muted-foreground">
            {text.length.toLocaleString()} characters
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={!text.trim()}
              className="px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground disabled:opacity-30 hover:bg-primary/90 transition-colors"
            >
              Attach
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
