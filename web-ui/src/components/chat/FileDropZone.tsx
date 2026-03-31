// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * FileDropZone — Wraps children with drag-and-drop file support.
 * Shows an overlay when files are dragged over the area.
 * Also handles ⌘V / Ctrl+V paste for images.
 */

"use client"

import { useState, useEffect, useCallback, DragEvent, ReactNode } from "react"
import { Upload } from "lucide-react"

interface FileDropZoneProps {
  /** Called when files are dropped or pasted. */
  onFiles: (files: FileList) => void
  /** Called when long text is pasted (200+ chars). */
  onLongTextPaste?: (text: string) => void
  /** When true, skip paste interception (e.g. snippet dialog is open). */
  pasteDisabled?: boolean
  /** Whether drop zone is active. */
  disabled?: boolean
  /** Child elements to wrap. */
  children: ReactNode
}

/**
 * Renders children with a drag-and-drop overlay for file attachment.
 * Listens for paste events to capture clipboard images and long text.
 *
 * @param props - FileDropZoneProps
 */
export function FileDropZone({ onFiles, onLongTextPaste, pasteDisabled, disabled, children }: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = useCallback(
    (e: DragEvent) => {
      if (disabled) return
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(true)
    },
    [disabled],
  )

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // Hide overlay when cursor leaves the drop zone entirely
    const related = e.relatedTarget as Node | null
    if (!related || !e.currentTarget.contains(related)) {
      setIsDragging(false)
    }
  }, [])

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(false)
      if (disabled) return
      if (e.dataTransfer.files.length > 0) {
        onFiles(e.dataTransfer.files)
      }
    },
    [disabled, onFiles],
  )

  // ⌘V / Ctrl+V paste handler for images
  useEffect(() => {
    if (disabled) return

    const handlePaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return

      const imageFiles: File[] = []
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile()
          if (file) imageFiles.push(file)
        }
      }

      if (imageFiles.length > 0) {
        e.preventDefault()
        const dt = new DataTransfer()
        imageFiles.forEach((f) => dt.items.add(f))
        onFiles(dt.files)
        return
      }

      // Detect long text paste (200+ chars) → snippet, unless pasteDisabled
      if (onLongTextPaste && !pasteDisabled) {
        const text = e.clipboardData?.getData("text/plain") || ""
        if (text.length > 200) {
          e.preventDefault()
          onLongTextPaste(text)
        }
      }
    }

    document.addEventListener("paste", handlePaste)
    return () => document.removeEventListener("paste", handlePaste)
  }, [disabled, pasteDisabled, onFiles, onLongTextPaste])

  return (
    <div
      className="relative h-full"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {children}

      {isDragging && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm border-2 border-dashed border-primary/50 rounded-lg">
          <div className="flex flex-col items-center gap-2 text-primary">
            <Upload className="h-8 w-8" />
            <span className="text-sm font-medium">Drop files to attach</span>
          </div>
        </div>
      )}
    </div>
  )
}
