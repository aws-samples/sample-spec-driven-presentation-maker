// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatMessage — Renders a single chat message with tool indicators.
 *
 * User messages: right-aligned bubble.
 * Assistant messages: left-aligned bubble with Markdown rendering.
 * Tool indicators appear below the message bubble:
 *   - Latest tool is remains visible
 *   - Older tools are collapsed behind a "N more tools" toggle
 *   - Expanded area has max-height with scroll
 *
 * @param role - "user" or "assistant"
 * @param content - Text content of the message
 * @param toolUses - Array of tool executions to display
 * @param isStreaming - Whether this message is still being streamed
 */

"use client"

import { useState, useEffect } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { ChevronRight, Sparkles, FileText as FileTextIcon, Image as ImageIcon } from "lucide-react"
import { ToolCard, ToolCardCompact } from "./ToolCard"
import { HearingCard } from "./HearingCard"
import { SnippetBlock } from "./SnippetBlock"
import { batchGetSlidePreviewUrls } from "@/services/deckService"

const MENTION_RE = /(@Page\s\d+|@\[[^\]]+\])/g
const SLIDE_PREVIEW_RE = /\[slide-preview:([a-f0-9]+):([a-z0-9_]+)\]/g
const COLOR_CODE_RE = /(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))\b/g

/**
 * Replace [slide-preview:deckId:slideId] markers with markdown images
 * when preview URLs are available, or remove them if not yet loaded.
 *
 * @param text - Message content with markers
 * @param urls - Map of "deckId:slideId" to presigned preview URL
 * @returns Cleaned content with markdown images
 */
function renderInlinePreviews(text: string, urls: Record<string, string>): string {
  return text.replace(SLIDE_PREVIEW_RE, (_, deckId, slideId) => {
    const url = urls[`${deckId}:${slideId}`]
    if (url) return `\n\n![${slideId}](${url})\n\n`
    // Show skeleton placeholder while loading
    return `\n\n![loading...](data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDgwIiBoZWlnaHQ9IjI3MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjMWExYTFhIiByeD0iOCIvPjxyZWN0IHg9IjQwJSIgeT0iNDUlIiB3aWR0aD0iMjAlIiBoZWlnaHQ9IjEwJSIgZmlsbD0iIzMzMyIgcng9IjQiLz48L3N2Zz4=)\n\n`
  })
}

/**
 * Highlight @Page N and @[DeckName] mentions within a text string,
 * and render inline color swatches next to hex color codes (#RGB / #RRGGBB).
 *
 * @param text - Raw text that may contain mentions or color codes
 * @returns Array of string and JSX elements with mentions/colors highlighted
 */
function highlightMentions(text: string): (string | React.JSX.Element)[] {
  // Combined regex: mentions OR hex color codes
  const COMBINED_RE = /(@Page\s\d+|@\[[^\]]+\]|#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b)/g
  const parts = text.split(COMBINED_RE)
  return parts.map((part, i) => {
    if (MENTION_RE.test(part)) {
      return <span key={i} className="text-blue-400 font-medium">{part}</span>
    }
    if (COLOR_CODE_RE.test(part)) {
      // Reset lastIndex since we use global regex for test
      COLOR_CODE_RE.lastIndex = 0
      return (
        <span key={i} className="inline-flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full border border-white/20 flex-none"
            style={{ backgroundColor: part }}
            aria-label={`Color ${part}`}
          />
          <code className="text-[12px] px-1 py-0.5 rounded bg-white/5">{part}</code>
        </span>
      )
    }
    return part
  })
}

/**
 * Markdown components override that highlights @mentions and color codes in text nodes.
 */
const markdownComponents = {
  p: ({ children, ...props }: React.ComponentProps<"p">) => (
    <p {...props}>
      {typeof children === "string" ? highlightMentions(children) : children}
    </p>
  ),
  li: ({ children, ...props }: React.ComponentProps<"li">) => (
    <li {...props}>
      {typeof children === "string" ? highlightMentions(children) : children}
    </li>
  ),
  code: ({ children, className, ...props }: React.ComponentProps<"code">) => {
    // Only decorate inline code (no language className = not a fenced block)
    if (!className && typeof children === "string" && /^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test(children.trim())) {
      const color = children.trim()
      return (
        <span className="inline-flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full border border-white/20 flex-none"
            style={{ backgroundColor: color }}
            aria-label={`Color ${color}`}
          />
          <code className={className} {...props}>{children}</code>
        </span>
      )
    }
    return <code className={className} {...props}>{children}</code>
  },
  img: ({ src, alt, ...props }: React.ComponentProps<"img">) => (
    <img
      src={src}
      alt={alt || "Slide preview"}
      className="inline-block h-[80px] rounded border border-border/30 mr-2 mb-2 cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
      {...props}
    />
  ),
}

export interface ToolUse {
  toolUseId: string
  name: string
  input?: Record<string, unknown>
  status?: "success" | "error"
  result?: Record<string, unknown>
}

export type MessageBlock = { type: "text"; text: string } | { type: "tool"; tool: ToolUse }

interface ChatMessageProps {
  role: "user" | "assistant"
  content: string
  toolUses?: ToolUse[]
  /** Ordered text/tool blocks for inline display. Falls back to content+toolUses if absent. */
  blocks?: MessageBlock[]
  snippets?: { label: string; text: string }[]
  attachments?: { fileName: string; fileType: string }[]
  isStreaming?: boolean
  /** Cognito ID token for fetching slide previews. */
  idToken?: string
  /** Callback to send a message (used by HearingCard). */
  onSend?: (text: string) => void
  /** Whether hearing cards should be disabled (a new message was sent). */
  hearingDisabled?: boolean
}

export function ChatMessage({ role, content, toolUses = [], blocks, snippets = [], attachments = [], isStreaming = false, idToken, onSend, hearingDisabled = false }: ChatMessageProps) {
  const isUser = role === "user"
  const [expanded, setExpanded] = useState(false)
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({})

  // Parse inline snippets from content (---snippet--- ... ---/snippet---)
  const snippetRegex = /---snippet---\n([\s\S]*?)---\/snippet---/g
  const inlineSnippets: { label: string; text: string }[] = []
  let match: RegExpExecArray | null
  let cleanContent = content
  while ((match = snippetRegex.exec(content)) !== null) {
    inlineSnippets.push({ label: "Text snippet", text: match[1].trim() })
  }
  if (inlineSnippets.length > 0) {
    cleanContent = content.replace(/\n*---snippet---\n[\s\S]*?---\/snippet---/g, "").trim()
  }
  // Strip [Attached: ...] markers from display text
  cleanContent = cleanContent.replace(/\[Attached:\s*[^\]]+\]\n*/g, "").trim()
  const allSnippets = [...inlineSnippets, ...snippets]

  // Fetch preview URLs for [slide-preview:deckId:slideId] markers
  useEffect(() => {
    if (isUser || !content || !idToken) return

    const matches: { deckId: string; slideId: string }[] = []
    let m: RegExpExecArray | null
    const re = new RegExp(SLIDE_PREVIEW_RE)
    while ((m = re.exec(content)) !== null) {
      matches.push({ deckId: m[1], slideId: m[2] })
    }
    if (matches.length === 0) return

    batchGetSlidePreviewUrls(matches, idToken).then((urlMap) => {
      const urls: Record<string, string> = {}
      for (const [key, url] of urlMap) {
        if (url) urls[key] = url
      }
      setPreviewUrls(urls)
    })
  }, [content, isUser, idToken])

  const latestTool = toolUses.length > 0 ? toolUses[toolUses.length - 1] : null
  const olderTools = toolUses.length > 1 ? toolUses.slice(0, -1) : []

  /** Render a text block as Markdown. */
  const renderTextBlock = (text: string, isLast: boolean) => {
    if (!text.trim()) return null
    // Apply snippet extraction to each text block
    const cleaned = text.replace(/\n*---snippet---\n[\s\S]*?---\/snippet---/g, "").trim()
    if (!cleaned) return null
    return (
      <div className={`text-[13px] leading-relaxed text-foreground/85 ${isLast && isStreaming ? "streaming-cursor" : ""}`}>
        <div className="prose prose-invert prose-sm max-w-none">
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {renderInlinePreviews(cleaned, previewUrls)}
          </Markdown>
        </div>
      </div>
    )
  }

  /** Whether to use inline blocks layout (streaming or blocks available). */
  const hasBlocks = blocks && blocks.length > 0

  return (
    <div className={`flex ${isUser ? "justify-end msg-user-enter" : "gap-2.5 msg-assistant-enter"}`}>
      {/* AI avatar */}
      {!isUser && (
        <div className="flex-none w-6 h-6 rounded-full flex items-center justify-center mt-0.5" style={{ background: "oklch(0.75 0.14 185 / 15%)" }}>
          <Sparkles className="h-3 w-3" style={{ color: "oklch(0.75 0.14 185)" }} />
        </div>
      )}
      <div className={isUser ? "max-w-[85%]" : "flex-1 min-w-0"}>
        {isUser ? (
          /* User bubble */
          <div className="text-[13px] leading-relaxed break-words px-3.5 py-2.5 rounded-2xl rounded-br-md bg-brand-teal-soft border border-brand-teal/15">
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {attachments.map((att, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] border border-border/40 bg-background/30">
                    {att.fileType.startsWith("image/")
                      ? <ImageIcon className="h-3 w-3 text-blue-400" />
                      : <FileTextIcon className="h-3 w-3 text-orange-400" />}
                    <span className="max-w-[140px] truncate">{att.fileName}</span>
                  </span>
                ))}
              </div>
            )}
            <span className="whitespace-pre-wrap">{MENTION_RE.test(cleanContent) ? highlightMentions(cleanContent) : cleanContent}</span>
          </div>
        ) : hasBlocks ? (
          /* Assistant: inline blocks layout */
          <div className="space-y-1.5">
            {blocks.map((block, i) =>
              block.type === "text" ? (
                <div key={`t-${i}`}>{renderTextBlock(block.text, i === blocks.length - 1)}</div>
              ) : block.tool.name === "hearing" && block.tool.input?.inference ? (
                <HearingCard
                  key={block.tool.toolUseId}
                  inference={String(block.tool.input.inference)}
                  questions={
                    (block.tool.input.questions as { id: string; type: "single_select" | "multi_select" | "free_text"; text: string; options?: string[]; recommended?: string | string[]; placeholder?: string }[])
                    || ["q0","q1","q2","q3","q4"].map((k, i) => block.tool.input?.[k] ? { id: k, ...block.tool.input[k] as object } : null).filter(Boolean) as { id: string; type: "single_select" | "multi_select" | "free_text"; text: string; options?: string[]; recommended?: string | string[]; placeholder?: string }[]
                  }
                  disabled={hearingDisabled}
                  onSubmit={(text) => onSend?.(text)}
                  onCancel={() => onSend?.("（スキップ）")}
                />
              ) : (
                <ToolCard
                  key={block.tool.toolUseId}
                  name={block.tool.name}
                  input={block.tool.input}
                  status={block.tool.status}
                  result={block.tool.result}
                  isActive={isStreaming && !block.tool.status && i === blocks.length - 1 && Object.keys(block.tool.input || {}).length === 0}
                />
              )
            )}
            {/* Thinking dots when no content yet */}
            {isStreaming && !cleanContent && toolUses.length === 0 && (
              <span className="inline-flex items-center gap-1.5 text-foreground/30 text-[12px]">
                <span className="flex gap-0.5">
                  <span className="w-1 h-1 rounded-full bg-brand-teal/60" style={{ animation: "cursor-blink 1.4s ease-in-out infinite" }} />
                  <span className="w-1 h-1 rounded-full bg-brand-teal/60" style={{ animation: "cursor-blink 1.4s ease-in-out 0.2s infinite" }} />
                  <span className="w-1 h-1 rounded-full bg-brand-teal/60" style={{ animation: "cursor-blink 1.4s ease-in-out 0.4s infinite" }} />
                </span>
              </span>
            )}
          </div>
        ) : (
          /* Assistant: fallback layout (history restore, no blocks) */
          <>
            {(cleanContent || (isStreaming && toolUses.length === 0)) && (
              <div className="text-[13px] leading-relaxed break-words text-foreground/85">
                {cleanContent ? (
                  <div className={`prose prose-invert prose-sm max-w-none ${isStreaming ? "streaming-cursor" : ""}`}>
                    <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {renderInlinePreviews(cleanContent, previewUrls)}
                    </Markdown>
                  </div>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-foreground/30 text-[12px]">
                    <span className="flex gap-0.5">
                      <span className="w-1 h-1 rounded-full bg-brand-teal/60" style={{ animation: "cursor-blink 1.4s ease-in-out infinite" }} />
                      <span className="w-1 h-1 rounded-full bg-brand-teal/60" style={{ animation: "cursor-blink 1.4s ease-in-out 0.2s infinite" }} />
                      <span className="w-1 h-1 rounded-full bg-brand-teal/60" style={{ animation: "cursor-blink 1.4s ease-in-out 0.4s infinite" }} />
                    </span>
                  </span>
                )}
              </div>
            )}

            {/* Tool cards — fallback (all at bottom) */}
            {toolUses.length > 0 && (
              <div className="mt-2 space-y-1.5">
                {latestTool && (
                  <ToolCard
                    name={latestTool.name}
                    input={latestTool.input}
                    status={latestTool.status}
                    result={latestTool.result}
                    isActive={isStreaming && !latestTool.status && (Object.keys(latestTool.input || {}).length === 0)}
                  />
                )}
                {olderTools.length > 0 && (
                  <>
                    <button
                      onClick={() => setExpanded(!expanded)}
                      className="inline-flex items-center gap-1 text-[11px] text-foreground/25 hover:text-foreground/40 transition-colors"
                      aria-expanded={expanded}
                    >
                      <ChevronRight className={`h-2.5 w-2.5 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`} />
                      {olderTools.length} more {olderTools.length === 1 ? "step" : "steps"}
                    </button>
                    {expanded && (
                      <div className="flex flex-col gap-0.5 pl-1">
                        {olderTools.map((t) => (
                          <ToolCardCompact key={t.toolUseId} name={t.name} input={t.input} />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </>
        )}

        {/* Snippets */}
        {allSnippets.length > 0 && (
          <div className="mt-1.5">
            {allSnippets.map((s, i) => (
              <SnippetBlock key={i} text={s.text} label={s.label} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
