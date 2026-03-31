// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * PlusMenu — Slack-style + button with popover menu for file attach and text snippet.
 */

"use client"

import { useRef, useState } from "react"
import { Plus, Paperclip, FileText } from "lucide-react"

interface PlusMenuProps {
  /** Called when user selects files via the file picker. */
  onFilesSelected: (files: FileList) => void
  /** Called when user wants to create a text snippet. */
  onSnippetRequest: () => void
  /** Whether the menu should be disabled. */
  disabled?: boolean
}

/**
 * Renders a + button that opens a popover with attach/snippet options.
 *
 * @param props - PlusMenuProps
 */
export function PlusMenu({ onFilesSelected, onSnippetRequest, disabled }: PlusMenuProps) {
  const [open, setOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const accept = ".txt,.md,.json,.pdf,.docx,.xlsx,.pptx,.png"

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        disabled={disabled}
        className="p-2.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 touch-target flex items-center justify-center"
        aria-label="Attach file or snippet"
        aria-expanded={open}
      >
        <Plus className="h-4 w-4" />
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />

          {/* Menu */}
          <div className="absolute bottom-full left-0 mb-2 z-50 bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[180px]">
            <button
              type="button"
              className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted transition-colors text-left"
              onClick={() => {
                setOpen(false)
                fileInputRef.current?.click()
              }}
            >
              <Paperclip className="h-4 w-4 text-muted-foreground" />
              Attach file
            </button>
            <button
              type="button"
              className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted transition-colors text-left"
              onClick={() => {
                setOpen(false)
                onSnippetRequest()
              }}
            >
              <FileText className="h-4 w-4 text-muted-foreground" />
              Text snippet
            </button>
          </div>
        </>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) {
            onFilesSelected(e.target.files)
            e.target.value = ""
          }
        }}
      />
    </div>
  )
}
