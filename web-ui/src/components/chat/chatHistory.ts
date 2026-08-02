// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Chat history parsing — converts persisted chat history into UI Messages.
 *
 * Two source formats:
 * - Local mode `.chat.json`: already in ChatPanel's internal Message shape
 * - Cloud mode (Bedrock Converse format): content blocks with toolUse /
 *   toolResult pairs that must be re-linked onto assistant messages
 *
 * Extracted from ChatPanel so the transformation is unit-testable.
 */

import type { ChatMessage } from "@/services/deckService"
import type { Message } from "@/hooks/useChatStream"
import type { ToolUse } from "./ChatMessage"
import { parseAttachedMarkers } from "@/lib/attachmentMarker"

/** Strip internal sdpm marker comments from persisted text. */
const MARKER_RE = /<!--sdpm:[^>]*-->\n?/g

/** Detect the Local-mode format: messages already carry toolUses. */
export function isLocalHistoryFormat(history: ChatMessage[]): boolean {
  return (history[0] as unknown as Record<string, unknown>)?.toolUses !== undefined
}

/** Local mode: history is already in the internal shape — just normalize. */
export function parseLocalHistory(history: ChatMessage[]): Message[] {
  return history.map((m) => {
    const raw = m as unknown as Record<string, unknown>
    return {
      role: ((raw.role as string) || "assistant") as "user" | "assistant",
      content: (typeof raw.content === "string" ? raw.content : "") as string,
      toolUses: (raw.toolUses as ToolUse[]) || [],
      blocks: (raw.blocks as ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[]) || undefined,
    }
  })
}

/** Derive attachment chips from valid v1 JSON markers in user text. */
function parseAttachments(text: string): { fileName: string; fileType: string }[] {
  const mimeMap: Record<string, string> = { pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation", pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif", svg: "image/svg+xml", json: "application/json", csv: "text/csv", html: "text/html", md: "text/markdown", txt: "text/plain" }
  return parseAttachedMarkers(text).map(({ name }) => {
    const ext = name.split(".").pop()?.toLowerCase() || ""
    return { fileName: name, fileType: mimeMap[ext] || "application/octet-stream" }
  })
}

/**
 * Cloud mode: parse Bedrock Converse-format history into Messages.
 *
 * User messages containing toolResult blocks are folded into the preceding
 * assistant message's matching toolUse (status + result), not emitted as
 * standalone messages.
 */
export function parseCloudHistory(history: ChatMessage[]): Message[] {
  const parsed: Message[] = []
  for (const m of history) {
    let text = ""
    const toolUses: ToolUse[] = []
    const snippets: { label: string; text: string }[] = []

    if (typeof m.content === "string") {
      text = m.content.replace(MARKER_RE, "")
    } else if (Array.isArray(m.content)) {
      const contentBlocks = m.content as unknown as Record<string, unknown>[]
      if (m.role === "user" && contentBlocks.some((b) => b.toolResult)) {
        for (const block of contentBlocks) {
          const b = block
          if (b.toolResult) {
            const tr = b.toolResult as Record<string, unknown>
            const tuId = tr.toolUseId as string
            const status = (tr.status as string) || "success"
            let resultText = ""
            for (const c of (tr.content as Record<string, unknown>[]) || []) {
              if (c.text) resultText += c.text as string
            }
            if (parsed.length > 0) {
              const prev = parsed[parsed.length - 1]
              if (prev.role === "assistant") {
                const matchedTool = prev.toolUses.find((t) => t.toolUseId === tuId)
                if (matchedTool) {
                  matchedTool.status = status as "success" | "error"
                  try { matchedTool.result = JSON.parse(resultText) } catch { matchedTool.result = resultText as unknown as Record<string, unknown> }
                }
                if (prev.blocks) {
                  for (const bl of prev.blocks) {
                    if (bl.type === "tool" && bl.tool.toolUseId === tuId) {
                      bl.tool.status = status as "success" | "error"
                      try { bl.tool.result = JSON.parse(resultText) } catch { bl.tool.result = resultText as unknown as Record<string, unknown> }
                    }
                  }
                }
              }
            }
          }
        }
        continue
      }

      for (const block of contentBlocks) {
        const b = block
        if (b.toolUse) {
          const tu = b.toolUse as Record<string, unknown>
          toolUses.push({
            toolUseId: (tu.toolUseId as string) || "",
            name: (tu.name as string) || "",
            input: (tu.input as Record<string, unknown>) || {},
          })
        } else if (b.text && toolUses.length === 0) {
          const cleaned = (b.text as string).replace(MARKER_RE, "")
          if (cleaned) text += (text ? "\n" : "") + cleaned
        }
      }
    }
    if (!text.trim() && toolUses.length === 0) continue
    const blocks: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] = []
    if (m.role === "assistant" && Array.isArray(m.content)) {
      for (const block of m.content) {
        const b = block as Record<string, unknown>
        if (b.text) {
          blocks.push({ type: "text", text: b.text as string })
        } else if (b.toolUse) {
          const tu = b.toolUse as Record<string, unknown>
          blocks.push({ type: "tool", tool: {
            toolUseId: (tu.toolUseId as string) || "",
            name: (tu.name as string) || "",
            input: (tu.input as Record<string, unknown>) || {},
          }})
        }
      }
    }
    const attachments = m.role === "user" ? parseAttachments(text) : []
    parsed.push({
      role: m.role as "user" | "assistant",
      content: text,
      toolUses,
      blocks: blocks.length > 0 ? blocks : undefined,
      snippets: snippets.length > 0 ? snippets : undefined,
      ...(attachments.length > 0 ? { attachments } : {}),
    })
  }
  return parsed
}
