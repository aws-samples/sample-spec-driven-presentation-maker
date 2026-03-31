// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SnippetBlock — Collapsible text snippet display in chat messages.
 * Shows first 3 lines with expand/collapse toggle.
 */

"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, FileText } from "lucide-react"

interface SnippetBlockProps {
  /** Full snippet text. */
  text: string
  /** Optional label for the snippet. */
  label?: string
}

/**
 * Renders a collapsible text block for long content.
 * Initially shows first 3 lines with character count.
 *
 * @param props - SnippetBlockProps
 */
export function SnippetBlock({ text, label }: SnippetBlockProps) {
  const [expanded, setExpanded] = useState(false)

  const lines = text.split("\n")
  const previewLines = lines.slice(0, 3).join("\n")
  const hasMore = lines.length > 3 || text.length > 200

  return (
    <div className="my-1 rounded-md border border-border/40 bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-3 py-1.5 text-left hover:bg-muted/50 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground flex-none" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground flex-none" />
        )}
        <FileText className="h-3 w-3 text-muted-foreground flex-none" />
        <span className="truncate text-muted-foreground">
          {label || "Text snippet"} ({text.length.toLocaleString()} chars)
        </span>
      </button>

      <div className="px-3 pb-2">
        <pre className="whitespace-pre-wrap break-words font-mono text-foreground/80">
          {expanded ? text : previewLines}
          {!expanded && hasMore && (
            <span className="text-muted-foreground">…</span>
          )}
        </pre>
      </div>
    </div>
  )
}
