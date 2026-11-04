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

/** Strands' background-task management tool: its synthetic get delivers a background result. */
const MANAGE_TOOL = "strands_manage_background_task"

/** A composer's report as the orchestrator received it (agent/session_runtime.py Session.report). */
const COMPOSER_NOTE_RE = /<composer_note group="(\d+)"(?: slugs="([^"]*)")?>([\s\S]*?)<\/composer_note>/g

/**
 * Text the agent received as a user message: composer notes become note messages, the
 * rest user messages, in order. Text without a note gives one user message, as before.
 */
function messagesFromText(text: string): Message[] {
  const notes = [...text.matchAll(COMPOSER_NOTE_RE)]
  if (notes.length === 0) {
    const message = userMessageFromText(text)
    return message.content.trim() ? [message] : []
  }
  const out: Message[] = []
  const pushText = (part: string) => {
    const message = userMessageFromText(part.trim())
    if (message.content.trim()) out.push(message)
  }
  let at = 0
  for (const note of notes) {
    pushText(text.slice(at, note.index))
    out.push({
      role: "assistant", content: "", toolUses: [],
      composerNote: { group: Number(note[1]), ...(note[2] ? { slugs: note[2] } : {}), text: note[3].trim() },
    })
    at = (note.index ?? 0) + note[0].length
  }
  pushText(text.slice(at))
  return out
}

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
 * standalone messages. Their text blocks are messages the user sent while the
 * agent worked (steers, folded in where they reached it): each becomes a user
 * message at that position.
 *
 * Background compose (Cloud): the `strands_manage_background_task` call that delivered a
 * result and its toolResult are dropped (the history API strips result bodies, so the
 * compose card keeps its dispatch result). A `<composer_note>` becomes a note message.
 */
export function parseCloudHistory(history: ChatMessage[]): Message[] {
  const parsed: Message[] = []
  const hiddenTools = new Set<string>()
  for (const m of history) {
    let text = ""
    const toolUses: ToolUse[] = []
    const snippets: { label: string; text: string }[] = []

    if (typeof m.content === "string") {
      text = m.content.replace(MARKER_RE, "")
    } else if (Array.isArray(m.content)) {
      const contentBlocks = m.content as unknown as Record<string, unknown>[]
      if (m.role === "user" && contentBlocks.some((b) => b.toolResult)) {
        const steers: string[] = []
        for (const block of contentBlocks) {
          const b = block
          if (typeof b.text === "string") steers.push(b.text)
          if (b.toolResult) {
            const tr = b.toolResult as Record<string, unknown>
            const tuId = tr.toolUseId as string
            if (hiddenTools.has(tuId)) continue
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
        for (const steer of steers) parsed.push(...messagesFromText(steer))
        continue
      }

      for (const block of contentBlocks) {
        const b = block
        if (b.toolUse) {
          const tu = b.toolUse as Record<string, unknown>
          if (tu.name === MANAGE_TOOL) {
            hiddenTools.add((tu.toolUseId as string) || "")
            continue
          }
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
    if (m.role === "user") {
      parsed.push(...messagesFromText(text))
      continue
    }
    const blocks: ({ type: "text"; text: string } | { type: "tool"; tool: ToolUse })[] = []
    if (m.role === "assistant" && Array.isArray(m.content)) {
      for (const block of m.content) {
        const b = block as Record<string, unknown>
        if (b.text) {
          blocks.push({ type: "text", text: b.text as string })
        } else if (b.toolUse) {
          const tu = b.toolUse as Record<string, unknown>
          if (tu.name === MANAGE_TOOL) continue
          blocks.push({ type: "tool", tool: {
            toolUseId: (tu.toolUseId as string) || "",
            name: (tu.name as string) || "",
            input: (tu.input as Record<string, unknown>) || {},
          }})
        }
      }
    }
    parsed.push({
      role: m.role as "user" | "assistant",
      content: text,
      toolUses,
      blocks: blocks.length > 0 ? blocks : undefined,
      snippets: snippets.length > 0 ? snippets : undefined,
    })
  }
  return parsed
}

/** A user message for raw text the agent received (markers stripped, attachment chips derived). */
export function userMessageFromText(text: string): Message {
  const content = text.replace(MARKER_RE, "")
  const attachments = parseAttachments(content)
  return { role: "user", content, toolUses: [], ...(attachments.length > 0 ? { attachments } : {}) }
}

/** The text a raw user message opens with (its string content or its first text block). */
function openingText(m: ChatMessage): string | undefined {
  if (typeof m.content === "string") return m.content
  if (!Array.isArray(m.content)) return undefined
  const blocks = m.content as unknown as Record<string, unknown>[]
  if (blocks.some((b) => b.toolResult)) return undefined
  const first = blocks.find((b) => typeof b.text === "string")
  return first ? (first.text as string) : undefined
}

/**
 * The history before the user message that opened a work period (`prompt`, exactly as
 * the agent received it): the last user message that opens with that text. The whole
 * history when there is none (the prompt is not stored yet).
 */
export function cutAtPrompt(history: ChatMessage[], prompt: string): ChatMessage[] {
  for (let i = history.length - 1; i >= 0; i--) {
    if (history[i].role === "user" && openingText(history[i]) === prompt) return history.slice(0, i)
  }
  return history
}
