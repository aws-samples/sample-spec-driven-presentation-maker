// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ToolCard — Work ledger row for tool executions in chat.
 *
 * Redesigned as a single vertical rail with ledger rows (commit log style).
 * Color answers only "who is working" via a left marker; state is communicated
 * through shape (dot = done, cursor arrow + name tag = active, muted dot = past).
 *
 * Four visual states:
 * - Active: cursor arrow marker + agent name tag + detail line
 * - Success: colored dot marker + result summary
 * - Error: red dot marker + error message (red reserved for real errors only)
 * - Compact: small muted dot + inline label
 *
 * Tool categories determine the agent color (who):
 * - compute → Layout (blue)
 * - build → Content (green)
 * - produce → Visual (purple)
 * - explore → Data (amber)
 * - hearing → Decorator (pink)
 * - other → neutral
 *
 * @param props.name - Tool function name
 * @param props.input - Tool input parameters
 * @param props.status - Completion status ("success" | "error")
 * @param props.result - Parsed tool result object
 * @param props.isActive - Whether the tool is currently executing
 */

"use client"

import {
  BookOpen, List, Search, FolderPlus, Pencil, Image,
  Trash2, ArrowUpDown, FolderOpen, Copy, Globe, Wrench,
  Check, FileText, Download, Play, Code, Palette,
  LayoutTemplate, Package, AlertCircle, RefreshCw,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useTranslations } from "next-intl"
import { ComposeCard } from "./compose/ComposeCard"
import { CAT, type ToolCategory } from "./toolPalette"
import { basename } from "@/lib/local/pathUtils"

interface ToolMeta {
  Icon: LucideIcon
  label: string
  category: ToolCategory
}


const ERR = { accent: "var(--state-error)", bg: "color-mix(in oklch, var(--state-error) 6%, transparent)", border: "color-mix(in oklch, var(--state-error) 18%, transparent)" }

/** Agent display names keyed by category (for active cursor name tag). */
const AGENT_NAMES: Record<ToolCategory, string> = {
  compute: "Layout",
  build: "Content",
  produce: "Visual",
  explore: "Data",
  hearing: "Decorator",
  other: "Agent",
}

/** Icon, label, and category per tool name. */
export const TOOL_META: Record<string, ToolMeta> = {
  // Native agent tools
  create_deck:        { Icon: FolderPlus,      label: "Creating deck",          category: "build" },
  write_slide:        { Icon: Pencil,          label: "Writing slide",          category: "build" },
  remove_slide:       { Icon: Trash2,          label: "Removing slide",         category: "build" },
  reorder_slides:     { Icon: ArrowUpDown,     label: "Reordering slides",      category: "build" },
  clone_deck:         { Icon: Copy,            label: "Cloning deck",           category: "build" },
  clone_slide:        { Icon: Copy,            label: "Cloning slide",          category: "build" },
  read_reference:     { Icon: BookOpen,        label: "Reading reference",      category: "explore" },
  list_references:    { Icon: List,            label: "Listing patterns",       category: "explore" },
  search_icons:       { Icon: Search,          label: "Searching icons",        category: "explore" },
  search_slides:      { Icon: Search,          label: "Searching slides",       category: "explore" },
  get_deck:           { Icon: FolderOpen,      label: "Loading deck",           category: "explore" },
  web_search:         { Icon: Globe,           label: "Web search",             category: "explore" },
  web_fetch:          { Icon: FileText,        label: "Fetching page",          category: "explore" },
  import_attachment:  { Icon: Download,        label: "Importing file",         category: "build" },
  generate_pptx:      { Icon: Download,        label: "Generating PPTX",        category: "produce" },
  generate_preview:   { Icon: Image,           label: "Generating preview",     category: "produce" },
  // MCP Server tools
  init_presentation:  { Icon: FolderPlus,      label: "Initializing deck",      category: "build" },
  analyze_template:   { Icon: LayoutTemplate,  label: "Analyzing template",     category: "explore" },
  start_presentation: { Icon: Play,            label: "Starting workflow",       category: "explore" },
  list_templates:     { Icon: LayoutTemplate,  label: "Listing templates",      category: "explore" },
  list_styles:        { Icon: List,            label: "Listing styles",         category: "explore" },
  apply_style:        { Icon: Palette,         label: "Applying style",         category: "build" },
  read_examples:      { Icon: BookOpen,        label: "Reading example",        category: "explore" },
  list_workflows:     { Icon: List,            label: "Listing workflows",      category: "explore" },
  read_workflows:     { Icon: BookOpen,        label: "Reading workflow",        category: "explore" },
  list_guides:        { Icon: List,            label: "Listing guides",         category: "explore" },
  read_guides:        { Icon: BookOpen,        label: "Reading guide",          category: "explore" },
  search_assets:      { Icon: Search,          label: "Searching assets",       category: "explore" },
  get_preview:        { Icon: Image,           label: "Getting preview",        category: "produce" },
  run_python:         { Icon: Code,            label: "Running code",           category: "compute" },
  run_style_python:   { Icon: Code,            label: "Building style",         category: "build" },
  grid:               { Icon: LayoutTemplate,  label: "Computing layout",       category: "compute" },
  code_to_slide:      { Icon: Code,            label: "Code to slide",          category: "build" },
  // MCP prefixed tools (Strands adds prefix from MCPClient)
  hearing:            { Icon: BookOpen,        label: "Asking questions",       category: "hearing" },
  spec_driven_presentation_maker_init_presentation:  { Icon: FolderPlus,     label: "Initializing deck",     category: "build" },
  spec_driven_presentation_maker_analyze_template:   { Icon: LayoutTemplate, label: "Analyzing template",    category: "explore" },
  spec_driven_presentation_maker_start_presentation: { Icon: Play,           label: "Starting workflow",      category: "explore" },
  spec_driven_presentation_maker_list_templates:     { Icon: LayoutTemplate, label: "Listing templates",     category: "explore" },
  spec_driven_presentation_maker_list_styles:      { Icon: List,           label: "Listing styles",        category: "explore" },
  spec_driven_presentation_maker_apply_style:      { Icon: Palette,        label: "Applying style",        category: "build" },
  spec_driven_presentation_maker_read_examples:      { Icon: BookOpen,       label: "Reading example",       category: "explore" },
  spec_driven_presentation_maker_list_workflows:     { Icon: List,           label: "Listing workflows",     category: "explore" },
  spec_driven_presentation_maker_read_workflows:     { Icon: BookOpen,       label: "Reading workflow",       category: "explore" },
  spec_driven_presentation_maker_list_guides:        { Icon: List,           label: "Listing guides",        category: "explore" },
  spec_driven_presentation_maker_read_guides:        { Icon: BookOpen,       label: "Reading guide",         category: "explore" },
  spec_driven_presentation_maker_search_assets:      { Icon: Search,         label: "Searching assets",      category: "explore" },
  spec_driven_presentation_maker_get_preview:        { Icon: Image,          label: "Getting preview",       category: "produce" },
  spec_driven_presentation_maker_generate_pptx:      { Icon: Download,       label: "Generating PPTX",       category: "produce" },
  spec_driven_presentation_maker_run_python:         { Icon: Code,           label: "Running code",          category: "compute" },
  spec_driven_presentation_maker_run_style_python:   { Icon: Code,           label: "Building style",        category: "build" },
  spec_driven_presentation_maker_code_to_slide:      { Icon: Code,           label: "Code to slide",         category: "build" },
  spec_driven_presentation_maker_grid:               { Icon: LayoutTemplate, label: "Computing layout",      category: "compute" },
  // Agent tools
  compose_slides:     { Icon: Package,         label: "Composing slides",       category: "produce" },
}

/**
 * Extract a meaningful detail string from tool input.
 *
 * @param name - Tool name
 * @param input - Tool input object
 * @returns Short descriptive string for display
 */
function getDetail(name: string, input?: Record<string, unknown>): string {
  if (!input || Object.keys(input).length === 0) return ""
  if ((name === "write_slide" || name.endsWith("_write_slide")) && input.slide_id) return String(input.slide_id)
  if ((name === "create_deck" || name.endsWith("_init_presentation")) && input.name) return String(input.name)
  if (input.purpose) { const p = String(input.purpose); return p.length > 40 ? p.slice(0, 40) + "…" : p }
  if (input.path) { const p = String(input.path); return basename(p) }
  if (input.template) return String(input.template)
  if (input.style) return String(input.style)
  if (input.keyword) return `"${input.keyword}"`
  if (input.query) { const q = String(input.query); return q.length > 30 ? `"${q.slice(0, 30)}…"` : `"${q}"` }
  const v = input.name || input.slide_id
  if (typeof v === "string" && v) return v.length > 30 ? v.slice(0, 30) + "…" : v
  return ""
}

/**
 * Extract a concise result summary for display.
 *
 * @param name - Tool name
 * @param result - Parsed tool result
 * @param status - Tool completion status
 * @returns Human-readable summary string
 */
function getResultSummary(name: string, result?: Record<string, unknown>, status?: string): string {
  if (status === "error") {
    if (result?.error) return String(result.error).slice(0, 60)
    return "Failed"
  }
  if (!result) return ""
  if (result.deckId) return `deck ${String(result.deckId).slice(0, 8)}`
  if (Array.isArray(result.results)) return `${result.results.length} found`
  if (Array.isArray(result.layouts)) return `${result.layouts.length} layouts`
  if (result.pptxUrl || result.s3Key) return "Ready"
  return ""
}

interface ToolCardProps {
  name: string
  input?: Record<string, unknown>
  status?: "success" | "error"
  result?: Record<string, unknown>
  isActive?: boolean
  /** Streaming progress events from tool execution. */
  streamMessages?: Record<string, unknown>[]
  /** Current deck slide IDs — used by ComposeCard for slug existence rendering. */
  deckSlugs?: string[]
  /** tool use id — forwarded to ComposeCard for soft-stop. */
  toolUseId?: string
  /** Session ID — forwarded to ComposeCard for soft-stop. */
  sessionId?: string
  /** Auth token — forwarded to ComposeCard (ID token: previews) / (Access token: cancel). */
  idToken?: string
  accessToken?: string
}

/** Strip MCP prefix from tool name for display lookup. */
export function stripPrefix(n: string): string {
  return n.replace(/^spec_driven_presentation_maker_/, "")
}

export function ToolCard({ name, input, status, result, isActive = false, streamMessages, deckSlugs, toolUseId, sessionId, idToken, accessToken }: ToolCardProps) {
  const t = useTranslations("tools")
  // Dispatch: compose_slides has a dedicated rich card.
  if (name === "compose_slides" || name.endsWith("_compose_slides")) {
    return (
      <ComposeCard
        input={input}
        status={status}
        result={result}
        isActive={isActive}
        streamMessages={streamMessages}
        deckSlugs={deckSlugs}
        toolUseId={toolUseId}
        sessionId={sessionId}
        accessToken={accessToken}
      />
    )
  }

  const meta = TOOL_META[stripPrefix(name)] || { Icon: Wrench, label: name.replace(/_/g, " "), category: "other" as ToolCategory }
  const label = t.has(stripPrefix(name)) ? t(stripPrefix(name)) : meta.label
  const isError = status === "error"
  const isComplete = !!status
  const colors = isError ? { ...CAT.other, accent: ERR.accent, bg: ERR.bg, border: ERR.border } : CAT[meta.category]
  const detail = getDetail(name, input)
  const summary = isComplete ? getResultSummary(name, result, status) : ""
  const agentName = AGENT_NAMES[meta.category]

  return (
    <div
      className={`ledger-row tool-card-enter group/tool py-1.5 ${isComplete && !isError ? "opacity-60" : ""}`}
      role="status"
      aria-label={`${isActive ? t("running") : isError ? t("failed") : t("completed")}: ${label}${detail ? ` — ${detail}` : ""}${summary ? ` — ${summary}` : ""}`}
      aria-live={isComplete ? "polite" : undefined}
    >
      <div className="ledger-marker">
        {isActive ? (
          <svg
            className="h-3 w-3 ledger-cursor ledger-cursor-active"
            viewBox="0 0 10 10"
            fill="none"
            aria-hidden="true"
          >
            <path d="M1 1 L9 5 L5 5.8 L3.5 9.5 Z" fill={colors.accent} />
          </svg>
        ) : isError ? (
          <div className="w-2 h-2 rounded-full tool-check-enter" style={{ background: ERR.accent }} aria-hidden="true" />
        ) : isComplete ? (
          <div className="w-1.5 h-1.5 rounded-full tool-check-enter" style={{ background: colors.accent }} aria-hidden="true" />
        ) : (
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--foreground-muted)", opacity: 0.4 }} aria-hidden="true" />
        )}
      </div>

      <div className="min-w-0">
        <div className="flex min-h-5 flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <meta.Icon className="h-3 w-3 flex-none" style={{ color: isError ? ERR.accent : colors.accent }} aria-hidden="true" />
          <span
            className="text-xs font-medium tracking-[-0.01em] transition-colors duration-300"
            style={{ color: isActive ? colors.accent : isError ? ERR.accent : isComplete ? "var(--foreground-secondary)" : "var(--foreground-muted)" }}
          >
            {label}
          </span>
          {detail && (
            <span className="max-w-[180px] truncate text-[11px] text-foreground-muted" style={{ fontFamily: "var(--font-geist-mono), ui-monospace, monospace" }}>
              {detail}
            </span>
          )}
          {summary && (
            <span className="max-w-[180px] truncate text-[11px] text-foreground-muted" style={{ fontFamily: "var(--font-geist-mono), ui-monospace, monospace" }}>
              → {summary}
            </span>
          )}
          {isActive && (
            <span
              className="rounded-sm px-1.5 py-0.5 text-[11px] font-semibold leading-none"
              style={{ color: colors.accent, background: `color-mix(in oklch, ${colors.accent} 10%, transparent)` }}
            >
              {agentName}
            </span>
          )}
        </div>
        {/* Streaming progress — grouped sub-tool feed (nested rail) */}
        {isActive && streamMessages && streamMessages.length > 0 && (() => {
          // Group events by group number for parallel display
          const groupMap = new Map<number, { status?: Record<string, unknown>; tools: Record<string, unknown>[] }>()
          const ungrouped: Record<string, unknown>[] = []

          for (const ev of streamMessages) {
            const g = typeof ev.group === "number" ? ev.group : 0
            if (g === 0) { ungrouped.push(ev); continue }
            if (!groupMap.has(g)) groupMap.set(g, { tools: [] })
            const entry = groupMap.get(g)!
            if (ev.status) {
              if (ev.status === "retrying") entry.tools = []
              entry.status = ev
            }
            else if (ev.tool) {
              entry.tools.push(ev)
              if (entry.status?.status === "retrying") entry.status = undefined
            }
            else if (ev.toolResult) {
              const tl = entry.tools.find((tl) => tl.toolUseId === ev.toolResult)
              if (tl) tl.toolStatus = ev.toolStatus
            }
          }

          // Ungrouped status messages (prefetching, building, etc.)
          const statusMsg = ungrouped.filter((e) => e.message).pop()

          return (
            <div className="mt-1.5 space-y-1">
              {statusMsg && (
                <p className="text-[11px] font-medium tracking-[-0.01em]" style={{ color: colors.accent }}>
                  {String(statusMsg.message)}
                </p>
              )}
              {[...groupMap.entries()].map(([g, { status: gStatus, tools }]) => {
                const totalGroups = gStatus?.total_groups ?? groupMap.size
                const slugs = gStatus?.slugs ?? tools[0]?.slugs ?? ""
                const isDone = gStatus?.status === "done"
                const isErr = gStatus?.status === "error" || gStatus?.status === "retry_failed"
                const isRetrying = gStatus?.status === "retrying"
                const retryAttempt = typeof gStatus?.attempt === "number" ? gStatus.attempt : 0
                const groupAccent = isErr ? ERR.accent : colors.accent

                return (
                  <div key={g} className="ledger-sub relative pl-3 border-l transition-colors duration-300" style={{ borderColor: `color-mix(in oklch, ${groupAccent} 20%, transparent)` }}>
                    {/* Group header with nested marker */}
                    <div className="flex items-center gap-1.5 py-0.5">
                      {/* Sub-marker */}
                      <div className="absolute left-0 -translate-x-1/2 flex-none">
                        {isDone ? (
                          <div className="w-1.5 h-1.5 rounded-full" style={{ background: groupAccent, opacity: 0.6 }} />
                        ) : isErr ? (
                          <div className="w-1.5 h-1.5 rounded-full" style={{ background: ERR.accent }} />
                        ) : isRetrying ? (
                          <RefreshCw className="w-2.5 h-2.5" style={{ color: groupAccent, animation: "tool-spinner 1s linear infinite" }} />
                        ) : (
                          <svg className="w-2.5 h-2.5" viewBox="0 0 10 10" aria-hidden="true">
                            <circle cx="5" cy="5" r="3.5" fill="none" stroke={groupAccent} strokeWidth="1" strokeDasharray="6 16" strokeLinecap="round" style={{ animation: "tool-spinner 1s linear infinite" }} />
                          </svg>
                        )}
                      </div>
                      <span className="text-[11px] font-medium tracking-[-0.01em]" style={{ color: `color-mix(in oklch, ${groupAccent} 80%, transparent)` }}>
                        {isRetrying ? `Retrying (${retryAttempt})` : `Group ${g}/${totalGroups}`} · {String(slugs)}
                        {isRetrying && !!gStatus?.error && (
                          <span className="ml-1 opacity-60" title={String(gStatus.error)}>— {String(gStatus.error).slice(0, 300)}</span>
                        )}
                      </span>
                    </div>
                    {/* Sub-tool list — show last 3 per group, old items faded */}
                    {!isDone && tools.slice(-3).map((ev, i) => {
                      const toolName = stripPrefix(String(ev.tool))
                      const sub = TOOL_META[toolName] || { Icon: Wrench, label: toolName.replace(/_/g, " "), category: "other" as ToolCategory }
                      const isToolErr = ev.toolStatus === "error"
                      const isToolDone = !!ev.toolStatus
                      const subColors = isToolErr ? { accent: ERR.accent } : CAT[sub.category]
                      const subDetail = getDetail(toolName, ev.input as Record<string, unknown> | undefined)
                      const isLast = i === Math.min(tools.length, 3) - 1
                      const showSpinner = isLast && !isToolDone
                      return (
                        <div key={`${g}-${ev.tool}-${i}`} className="flex items-center gap-1.5 py-0.5 ml-1" style={{ opacity: isLast ? 1 : 0.4 }}>
                          {/* Sub-tool marker */}
                          <div className="flex-none w-1.5 h-1.5 flex items-center justify-center">
                            {showSpinner ? (
                              <div className="w-1 h-1 rounded-full" style={{ background: subColors.accent, animation: "tool-pulse 1.5s ease-in-out infinite" }} />
                            ) : isToolErr ? (
                              <div className="w-1.5 h-1.5 rounded-full" style={{ background: ERR.accent }} />
                            ) : isToolDone ? (
                              <div className="w-1 h-1 rounded-full" style={{ background: subColors.accent, opacity: 0.6 }} />
                            ) : (
                              <div className="w-1 h-1 rounded-full" style={{ background: subColors.accent, opacity: 0.3 }} />
                            )}
                          </div>
                          <span className="text-[11px] truncate" style={{ color: isLast ? "var(--foreground-secondary)" : "var(--foreground-muted)" }}>
                            {sub.label}{subDetail ? ` · ${subDetail}` : ""}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          )
        })()}
      </div>
    </div>
  )
}

/**
 * ToolCardCompact — Minimal inline display for collapsed older tools.
 * Shows a small muted dot + label (past/compact state in the ledger).
 *
 * @param props.name - Tool function name
 * @param props.input - Tool input parameters
 */
export function ToolCardCompact({ name, input }: { name: string; input?: Record<string, unknown> }) {
  const t = useTranslations("tools")
  const meta = TOOL_META[stripPrefix(name)] || { Icon: Wrench, label: name.replace(/_/g, " "), category: "other" as ToolCategory }
  const label = t.has(stripPrefix(name)) ? t(stripPrefix(name)) : meta.label
  const colors = CAT[meta.category]
  const detail = getDetail(name, input)

  return (
    <span className="ledger-compact inline-flex items-center gap-1.5 text-[11px] text-foreground/30 py-0.5">
      {/* Small muted dot marker */}
      <span
        className="flex-none w-1 h-1 rounded-full"
        style={{ background: colors.accent, opacity: 0.4 }}
        aria-hidden="true"
      />
      <span>{label}</span>
      {detail && <span className="opacity-60 truncate max-w-[150px]">{detail}</span>}
    </span>
  )
}
