// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AttachmentPreview — Shows attached files and text snippets above the chat
 * input before sending. Displays file name, size, type icon, snippet preview,
 * and remove buttons.
 */

"use client"

import { X, FileText, Image, File, AlignLeft } from "lucide-react"

export interface Attachment {
  id: string
  file: File
  status: "pending" | "uploading" | "completed" | "failed"
  uploadId?: string
  extractedText?: string
  imageUrl?: string
  error?: string
}

export interface SnippetAttachment {
  id: string
  text: string
}

interface AttachmentPreviewProps {
  /** List of attached files. */
  attachments: Attachment[]
  /** List of attached text snippets. */
  snippets?: SnippetAttachment[]
  /** Called when user removes an attachment. */
  onRemove: (id: string) => void
  /** Called when user removes a snippet. */
  onRemoveSnippet?: (id: string) => void
  /** Called when user clicks a snippet to edit it. */
  onEditSnippet?: (id: string) => void
}

/**
 * Format file size for display.
 *
 * @param bytes - File size in bytes
 * @returns Human-readable size string
 */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

/**
 * Get icon component based on file MIME type.
 *
 * @param type - MIME type string
 * @returns Lucide icon component
 */
function FileIcon({ type }: { type: string }) {
  if (type.startsWith("image/")) return <Image className="h-4 w-4 text-blue-400" />
  if (type.includes("pdf") || type.includes("word") || type.includes("sheet") || type.includes("presentation")) {
    return <FileText className="h-4 w-4 text-orange-400" />
  }
  return <File className="h-4 w-4 text-muted-foreground" />
}

/**
 * Renders a horizontal list of attachment and snippet chips above the input area.
 *
 * @param props - AttachmentPreviewProps
 */
export function AttachmentPreview({ attachments, snippets, onRemove, onRemoveSnippet, onEditSnippet }: AttachmentPreviewProps) {
  const hasItems = attachments.length > 0 || (snippets && snippets.length > 0)
  if (!hasItems) return null

  return (
    <div className="flex flex-wrap gap-2 px-1 pb-2">
      {attachments.map((att) => (
        <div
          key={att.id}
          className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border ${
            att.status === "failed"
              ? "border-red-500/40 bg-red-500/10"
              : att.status === "uploading"
                ? "border-border/40 bg-muted/50 animate-pulse"
                : "border-border/40 bg-muted/50"
          }`}
        >
          <FileIcon type={att.file.type} />
          <span className="max-w-[120px] truncate">{att.file.name}</span>
          <span className="text-muted-foreground">{formatSize(att.file.size)}</span>
          <button
            type="button"
            onClick={() => onRemove(att.id)}
            className="ml-0.5 p-0.5 rounded hover:bg-muted-foreground/20 transition-colors"
            aria-label={`Remove ${att.file.name}`}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}

      {snippets?.map((snip) => (
        <div
          key={snip.id}
          className="group relative flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-blue-500/30 bg-blue-500/5 cursor-pointer hover:border-blue-500/50 transition-colors"
          onClick={() => onEditSnippet?.(snip.id)}
        >
          <AlignLeft className="h-4 w-4 text-blue-400 flex-none" />
          <span className="max-w-[160px] truncate text-muted-foreground">
            {snip.text.slice(0, 60)}{snip.text.length > 60 ? "…" : ""}
          </span>
          <span className="text-muted-foreground/60">{snip.text.length.toLocaleString()}c</span>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRemoveSnippet?.(snip.id) }}
            className="ml-0.5 p-0.5 rounded hover:bg-muted-foreground/20 transition-colors"
            aria-label="Remove snippet"
          >
            <X className="h-3 w-3" />
          </button>

          {/* Hover preview tooltip */}
          <div className="hidden group-hover:block absolute bottom-full left-0 mb-2 z-50 w-[300px] max-h-[200px] overflow-y-auto bg-popover border border-border rounded-lg shadow-lg p-3 text-xs whitespace-pre-wrap break-words pointer-events-none">
            {snip.text.slice(0, 1000)}{snip.text.length > 1000 ? "\n…" : ""}
          </div>
        </div>
      ))}
    </div>
  )
}
