// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * BriefDocumentView — Contract-document metaphor for the spec brief.
 *
 * Two layers:
 * 1. react-markdown components mapping for robust editorial h1/h2/p/table
 *    that works for arbitrary markdown (graceful degradation).
 * 2. Progressive enhancement for literal [MUST], [MUST NOT], [PREFER] markers
 *    as chips, Materials table styling, and preserved HEX swatches.
 *
 * The achromatic deliverable surface uses --font-document (Fraunces) for
 * headings via the existing document-surface CSS scope.
 *
 * Approval status is derived from outline existence (outline.md as the
 * workflow gate per the spec-driven approach).
 */

"use client"

import React, { useMemo } from "react"
import Markdown from "react-markdown"
import type { Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { FileCheck2, FileClock } from "lucide-react"
import { useTranslations } from "next-intl"
import { renderColorSwatches } from "./colorSwatches"

// ── Requirement chip patterns ──────────────────────────────────────────────

/** Matches [MUST], [MUST NOT], [PREFER] markers in text. */
const REQUIREMENT_RE = /\[(MUST NOT|MUST|PREFER)\]/g

/** Chip style variants for requirement markers. */
const CHIP_STYLES: Record<string, string> = {
  MUST: "bg-foreground/90 text-background font-semibold",
  "MUST NOT": "requirement-must-not bg-transparent text-foreground font-semibold border border-foreground/60",
  PREFER: "bg-transparent text-foreground/80 font-medium border border-dashed border-foreground/40",
}

/**
 * Render requirement chips inline — progressive enhancement.
 * Transforms [MUST], [MUST NOT], [PREFER] markers into styled chips.
 * Falls back to plain text for unrecognized patterns.
 */
function renderRequirementChips(text: string): (string | React.ReactElement)[] {
  const parts: (string | React.ReactElement)[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  const regex = new RegExp(REQUIREMENT_RE.source, "g")
  while ((match = regex.exec(text)) !== null) {
    // Text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const marker = match[1] // "MUST" | "MUST NOT" | "PREFER"
    const chipClass = CHIP_STYLES[marker]
    if (chipClass) {
      parts.push(
        <span
          key={`chip-${match.index}`}
          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] tracking-wide align-baseline ${chipClass}`}
          role="img"
          aria-label={marker}
        >
          {marker}
        </span>
      )
    } else {
      parts.push(match[0])
    }
    lastIndex = regex.lastIndex
  }
  // Remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

/**
 * Process text content: apply requirement chips first, then color swatches.
 */
function processTextContent(text: string): (string | React.ReactElement)[] {
  const chipProcessed = renderRequirementChips(text)
  // Apply color swatches to remaining string segments
  return chipProcessed.flatMap((segment, i) => {
    if (typeof segment === "string") {
      const swatched = renderColorSwatches(segment)
      return swatched.map((s, j) =>
        typeof s === "string" ? s : React.cloneElement(s, { key: `sw-${i}-${j}` })
      )
    }
    return segment
  })
}

/**
 * Check if a table is a "Materials" table by examining rendered text content.
 * Looks for keywords in the first row (header area).
 */
function isMaterialsTable(children: React.ReactNode): boolean {
  // Walk the React tree to find header-related text
  const text = getTextContent(children)
  // Only check the first line-ish of text (roughly the header row)
  const firstLine = text.slice(0, 100)
  return /material|素材|asset|color|colour/i.test(firstLine)
}

/** Extract text content from React nodes recursively. */
function getTextContent(node: React.ReactNode): string {
  if (typeof node === "string") return node
  if (typeof node === "number") return String(node)
  if (!node) return ""
  if (Array.isArray(node)) return node.map(getTextContent).join("")
  if (React.isValidElement(node)) {
    return getTextContent((node.props as { children?: React.ReactNode }).children)
  }
  return ""
}

// ── Markdown component overrides (Layer 1 — editorial typography) ──────────

/**
 * Editorial markdown components — achromatic document surface.
 * These render properly for arbitrary markdown; the progressive enhancement
 * (chips, materials table) layers on top.
 */
const briefComponents = {
  h1: ({ children, ...props }: React.ComponentProps<"h1">) => (
    <h1
      className="text-2xl font-semibold tracking-tight mt-0 mb-4 pb-3 border-b border-foreground/[0.08]"
      {...props}
    >
      {typeof children === "string" ? processTextContent(children) : children}
    </h1>
  ),
  h2: ({ children, ...props }: React.ComponentProps<"h2">) => (
    <h2
      className="text-lg font-semibold tracking-tight mt-8 mb-3"
      {...props}
    >
      {typeof children === "string" ? processTextContent(children) : children}
    </h2>
  ),
  h3: ({ children, ...props }: React.ComponentProps<"h3">) => (
    <h3
      className="text-[15px] font-medium mt-6 mb-2 text-foreground/80"
      {...props}
    >
      {typeof children === "string" ? processTextContent(children) : children}
    </h3>
  ),
  p: ({ children, ...props }: React.ComponentProps<"p">) => (
    <p className="text-sm leading-relaxed mb-3 text-foreground/90" {...props}>
      {typeof children === "string" ? processTextContent(children) : children}
    </p>
  ),
  li: ({ children, ...props }: React.ComponentProps<"li">) => (
    <li className="text-sm leading-relaxed text-foreground/90" {...props}>
      {typeof children === "string" ? processTextContent(children) : children}
    </li>
  ),
  ul: ({ children, ...props }: React.ComponentProps<"ul">) => (
    <ul className="list-disc pl-5 mb-3 space-y-1 marker:text-foreground/30" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }: React.ComponentProps<"ol">) => (
    <ol className="list-decimal pl-5 mb-3 space-y-1 marker:text-foreground/30" {...props}>
      {children}
    </ol>
  ),
  table: ({ children, ...props }: React.ComponentProps<"table">) => {
    const materials = isMaterialsTable(children)
    return (
      <div className="my-4 overflow-x-auto rounded-lg border border-foreground/[0.08]">
        <table
          className={`w-full text-sm border-collapse ${materials ? "brief-materials-table" : ""}`}
          {...props}
        >
          {children}
        </table>
      </div>
    )
  },
  thead: ({ children, ...props }: React.ComponentProps<"thead">) => (
    <thead className="bg-foreground/[0.04]" {...props}>{children}</thead>
  ),
  th: ({ children, ...props }: React.ComponentProps<"th">) => (
    <th
      className="text-left text-xs font-semibold uppercase tracking-wider text-foreground/60 px-3 py-2 border-b border-foreground/[0.08]"
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ children, ...props }: React.ComponentProps<"td">) => (
    <td className="px-3 py-2 border-b border-foreground/[0.04] text-foreground/80" {...props}>
      {typeof children === "string" ? processTextContent(children) : children}
    </td>
  ),
  tr: ({ children, ...props }: React.ComponentProps<"tr">) => (
    <tr className="hover:bg-foreground/[0.02] transition-colors" {...props}>{children}</tr>
  ),
  blockquote: ({ children, ...props }: React.ComponentProps<"blockquote">) => (
    <blockquote
      className="border-l-2 border-foreground/20 pl-4 my-4 italic text-foreground/70"
      {...props}
    >
      {children}
    </blockquote>
  ),
  hr: ({ ...props }: React.ComponentProps<"hr">) => (
    <hr className="border-foreground/[0.08] my-6" {...props} />
  ),
  code: ({ children, className, ...props }: React.ComponentProps<"code">) => {
    // Inline code with HEX color swatch
    if (!className && typeof children === "string" && /^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test(children.trim())) {
      const color = children.trim()
      return (
        <span className="inline-flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full border border-foreground/20 flex-none"
            style={{ backgroundColor: color }}
            aria-label={`Color ${color}`}
          />
          <code className="text-xs px-1 py-0.5 rounded bg-foreground/[0.06]" {...props}>{children}</code>
        </span>
      )
    }
    return (
      <code className={`text-xs px-1 py-0.5 rounded bg-foreground/[0.06] ${className || ""}`} {...props}>
        {children}
      </code>
    )
  },
  strong: ({ children, ...props }: React.ComponentProps<"strong">) => (
    <strong className="font-semibold text-foreground" {...props}>{children}</strong>
  ),
}

// ── Approval Status Bar ────────────────────────────────────────────────────

interface ApprovalStatusProps {
  approved: boolean
}

function ApprovalStatus({ approved }: ApprovalStatusProps) {
  const t = useTranslations("briefDocument")

  if (approved) {
    return (
      <div className="flex items-center gap-2 text-xs text-foreground/60" role="status" aria-label={t("approvedAria")}>
        <FileCheck2 className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{t("approved")}</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 text-xs text-foreground/50" role="status" aria-label={t("pendingAria")}>
      <FileClock className="h-3.5 w-3.5" aria-hidden="true" />
      <span>{t("pending")}</span>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export interface BriefDocumentViewProps {
  /** Markdown content of the brief. */
  content: string
  /** Whether outline exists (= brief is approved per workflow gate). */
  outlineExists: boolean
}

export function BriefDocumentView({ content, outlineExists }: BriefDocumentViewProps) {
  const t = useTranslations("briefDocument")

  const approved = useMemo(() => outlineExists, [outlineExists])

  return (
    <div className="content-enter flex-1 overflow-y-auto px-6 sm:px-8 py-6">
      {/* Document header — contract metaphor */}
      <div className="max-w-3xl mx-auto mb-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono text-foreground/40 tracking-wide">
            {t("filePath")}
          </span>
          <ApprovalStatus approved={approved} />
        </div>
        <div className="mt-2 h-px bg-foreground/[0.08]" />
      </div>

      {/* Document body — editorial markdown rendering */}
      <article className="document-surface prose prose-invert prose-sm max-w-3xl mx-auto spec-prose">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={briefComponents as Components}
        >
          {content}
        </Markdown>
      </article>
    </div>
  )
}
