// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ToolCard — Premium activity card for tool executions in chat.
 *
 * Three visual states with smooth transitions:
 * - Active: Animated gradient border + spinner + pulse glow
 * - Success: Accent check + result summary slide-in
 * - Error: Red accent + error message
 *
 * Tool categories determine the accent color:
 * - build: teal (creating/modifying)
 * - explore: amber (reading/searching)
 * - produce: violet (generating output)
 * - compute: cyan (code execution)
 * - other: neutral
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
  LayoutTemplate, Package, AlertCircle, Ruler,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

type ToolCategory = "build" | "explore" | "produce" | "compute" | "other"

interface ToolMeta {
  Icon: LucideIcon
  label: string
  category: ToolCategory
}

/** Accent palette per category — oklch for perceptual uniformity. */
const CAT: Record<ToolCategory, { accent: string; bg: string; glow: string; border: string }> = {
  build:   { accent: "oklch(0.75 0.14 185)", bg: "oklch(0.75 0.14 185 / 6%)",  glow: "oklch(0.75 0.14 185 / 12%)", border: "oklch(0.75 0.14 185 / 18%)" },
  explore: { accent: "oklch(0.80 0.14 80)",  bg: "oklch(0.80 0.14 80 / 6%)",   glow: "oklch(0.80 0.14 80 / 12%)",  border: "oklch(0.80 0.14 80 / 18%)" },
  produce: { accent: "oklch(0.72 0.16 300)", bg: "oklch(0.72 0.16 300 / 6%)",  glow: "oklch(0.72 0.16 300 / 12%)", border: "oklch(0.72 0.16 300 / 18%)" },
  compute: { accent: "oklch(0.78 0.12 220)", bg: "oklch(0.78 0.12 220 / 6%)",  glow: "oklch(0.78 0.12 220 / 12%)", border: "oklch(0.78 0.12 220 / 18%)" },
  other:   { accent: "oklch(0.55 0 0)",      bg: "oklch(0.55 0 0 / 4%)",       glow: "oklch(0.55 0 0 / 8%)",       border: "oklch(0.55 0 0 / 12%)" },
}

const ERR = { accent: "oklch(0.65 0.2 25)", bg: "oklch(0.65 0.2 25 / 6%)", border: "oklch(0.65 0.2 25 / 18%)" }

/** Icon, label, and category per tool name. */
const TOOL_META: Record<string, ToolMeta> = {
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
  read_uploaded_file: { Icon: FileText,        label: "Reading file",           category: "explore" },
  generate_pptx:      { Icon: Download,        label: "Generating PPTX",        category: "produce" },
  generate_preview:   { Icon: Image,           label: "Generating preview",     category: "produce" },
  measure_slides:     { Icon: Ruler,           label: "Measuring slides",       category: "produce" },
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
  list_asset_sources: { Icon: Package,         label: "Listing asset sources",  category: "explore" },
  get_preview:        { Icon: Image,           label: "Getting preview",        category: "produce" },
  run_python:         { Icon: Code,            label: "Running code",           category: "compute" },
  code_to_slide:      { Icon: Code,            label: "Code to slide",          category: "build" },
  pptx_to_json:       { Icon: FileText,        label: "Converting PPTX",        category: "explore" },
  grid:               { Icon: LayoutTemplate,  label: "Computing layout",       category: "compute" },
  // MCP prefixed tools (Strands adds prefix from MCPClient)
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
  spec_driven_presentation_maker_list_asset_sources: { Icon: Package,        label: "Listing asset sources", category: "explore" },
  spec_driven_presentation_maker_get_preview:        { Icon: Image,          label: "Getting preview",       category: "produce" },
  spec_driven_presentation_maker_generate_pptx:      { Icon: Download,       label: "Generating PPTX",       category: "produce" },
  spec_driven_presentation_maker_measure_slides:     { Icon: Ruler,          label: "Measuring slides",      category: "produce" },
  spec_driven_presentation_maker_run_python:         { Icon: Code,           label: "Running code",          category: "compute" },
  spec_driven_presentation_maker_code_to_slide:      { Icon: Code,           label: "Code to slide",         category: "build" },
  spec_driven_presentation_maker_pptx_to_json:       { Icon: FileText,       label: "Converting PPTX",       category: "explore" },
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
  if ((name === "measure_slides" || name.endsWith("_measure_slides")) && input.slide_numbers) {
    const nums = input.slide_numbers as number[]
    return `Pages ${nums.join(", ")}`
  }
  if ((name === "measure_slides" || name.endsWith("_measure_slides")) && !input.slide_numbers) return "All slides"
  if (input.purpose) { const p = String(input.purpose); return p.length > 40 ? p.slice(0, 40) + "…" : p }
  if (input.path) { const p = String(input.path); return p.split("/").pop() || p }
  if (input.template) return String(input.template)
  if (input.keyword) return `"${input.keyword}"`
  if (input.query) { const q = String(input.query); return q.length > 30 ? `"${q.slice(0, 30)}…"` : `"${q}"` }
  const v = input.name || input.slide_id || input.deck_id
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
  if ((name === "measure_slides" || name.endsWith("_measure_slides")) && Array.isArray(result.slides)) {
    const overflows = (result.slides as Record<string, unknown>[]).filter((s) => {
      const els = s.overflow_elements
      return Array.isArray(els) && els.length > 0
    }).length
    return overflows > 0 ? `${overflows} overflow${overflows > 1 ? "s" : ""} detected` : "All clear"
  }
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
}

/** Strip MCP prefix from tool name for display lookup. */
function stripPrefix(n: string): string {
  return n.replace(/^spec_driven_presentation_maker_/, "")
}

export function ToolCard({ name, input, status, result, isActive = false, streamMessages }: ToolCardProps) {
  const meta = TOOL_META[name] || { Icon: Wrench, label: name.replace(/_/g, " "), category: "other" as ToolCategory }
  const isError = status === "error"
  const isComplete = !!status
  const colors = isError ? { ...CAT.other, accent: ERR.accent, bg: ERR.bg, border: ERR.border } : CAT[meta.category]
  const detail = getDetail(name, input)
  const summary = isComplete ? getResultSummary(name, result, status) : ""
  const { Icon } = meta

  return (
    <div
      className="tool-card-enter group/tool relative flex items-center gap-2.5 pl-3 pr-3.5 py-2 rounded-xl transition-all duration-500"
      style={{
        background: isActive ? colors.bg : isComplete ? colors.bg : "transparent",
        boxShadow: isActive ? `0 0 20px ${colors.glow}, inset 0 0 0 1px ${colors.border}` : isComplete ? `inset 0 0 0 1px ${colors.border}` : "inset 0 0 0 1px oklch(1 0 0 / 4%)",
      }}
      role="status"
      aria-label={`${isActive ? "Running" : isError ? "Failed" : "Completed"}: ${meta.label}${detail ? ` — ${detail}` : ""}${summary ? ` — ${summary}` : ""}`}
      aria-live={isComplete ? "polite" : undefined}
    >
      {/* Animated gradient border for active state */}
      {isActive && (
        <div
          className="absolute inset-0 rounded-xl pointer-events-none"
          style={{
            background: `linear-gradient(135deg, ${colors.accent}15, transparent 40%, ${colors.accent}08)`,
            animation: "tool-active-shimmer 2s ease-in-out infinite",
          }}
        />
      )}

      {/* Icon container with state transitions */}
      <div
        className="relative flex-none w-7 h-7 rounded-lg flex items-center justify-center transition-all duration-300"
        style={{
          background: isActive ? `${colors.accent}18` : isComplete ? `${colors.accent}12` : "oklch(1 0 0 / 4%)",
        }}
      >
        {isActive ? (
          /* Spinning ring — custom SVG for premium feel */
          <svg className="absolute inset-0 w-7 h-7" viewBox="0 0 28 28">
            <circle
              cx="14" cy="14" r="12"
              fill="none"
              stroke={colors.accent}
              strokeWidth="1.5"
              strokeDasharray="20 56"
              strokeLinecap="round"
              style={{ animation: "tool-spinner 1.2s linear infinite" }}
            />
          </svg>
        ) : isComplete ? (
          /* Success/error indicator ring */
          <svg className="absolute inset-0 w-7 h-7 tool-ring-enter" viewBox="0 0 28 28">
            <circle
              cx="14" cy="14" r="12"
              fill="none"
              stroke={colors.accent}
              strokeWidth="1.5"
              strokeDasharray="75.4"
              strokeDashoffset="0"
              strokeLinecap="round"
              opacity="0.3"
            />
          </svg>
        ) : null}

        {/* Center icon */}
        {isComplete && !isError ? (
          <Check
            className="h-3 w-3 tool-check-enter"
            style={{ color: colors.accent }}
          />
        ) : isComplete && isError ? (
          <AlertCircle
            className="h-3 w-3 tool-check-enter"
            style={{ color: ERR.accent }}
          />
        ) : (
          <Icon
            className="h-3 w-3 transition-colors duration-300"
            style={{ color: isActive ? colors.accent : "oklch(0.50 0 0)" }}
          />
        )}
      </div>

      {/* Content */}
      <div className="relative flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span
            className="text-[12px] font-medium tracking-[-0.01em] transition-colors duration-300"
            style={{ color: isActive ? colors.accent : isComplete ? colors.accent : "oklch(0.50 0 0)" }}
          >
            {meta.label}
          </span>
        </div>
        {/* Detail line: input params or result summary */}
        {(detail || summary) && (
          <p
            className="text-[11px] truncate mt-0.5 leading-tight transition-all duration-300"
            style={{ color: isComplete ? `${colors.accent}99` : "oklch(1 0 0 / 25%)" }}
          >
            {summary || detail}
          </p>
        )}
        {/* Streaming progress — sub-tool activity feed */}
        {isActive && streamMessages && streamMessages.length > 0 && (() => {
          // Group events by group number for parallel display
          const groupMap = new Map<number, { status?: Record<string, unknown>; tools: Record<string, unknown>[] }>()
          const ungrouped: Record<string, unknown>[] = []

          for (const ev of streamMessages) {
            const g = typeof ev.group === "number" ? ev.group : 0
            if (g === 0) { ungrouped.push(ev); continue }
            if (!groupMap.has(g)) groupMap.set(g, { tools: [] })
            const entry = groupMap.get(g)!
            if (ev.status) entry.status = ev
            else if (ev.tool) entry.tools.push(ev)
          }

          // Ungrouped status messages (prefetching, building, etc.)
          const statusMsg = ungrouped.filter((e) => e.message).pop()

          return (
            <div className="mt-1.5 space-y-1.5">
              {statusMsg && (
                <p className="text-[11px] font-medium tracking-[-0.01em]" style={{ color: `${colors.accent}cc` }}>
                  {String(statusMsg.message)}
                </p>
              )}
              {[...groupMap.entries()].map(([g, { status: gStatus, tools }]) => {
                const totalGroups = gStatus?.total_groups ?? groupMap.size
                const slugs = gStatus?.slugs ?? tools[0]?.slugs ?? ""
                const isDone = gStatus?.status === "done"
                const isErr = gStatus?.status === "error" || gStatus?.status === "retry_failed"
                const isRetrying = gStatus?.status === "retrying"
                const groupAccent = isErr ? ERR.accent : colors.accent

                return (
                  <div key={g} className="rounded-lg px-2 py-1.5 transition-all duration-300" style={{ background: `${groupAccent}08` }}>
                    {/* Group header */}
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <div className="flex-none w-3.5 h-3.5 rounded flex items-center justify-center" style={{ background: `${groupAccent}15` }}>
                        {isDone ? (
                          <Check className="h-2 w-2" style={{ color: groupAccent }} />
                        ) : isErr ? (
                          <AlertCircle className="h-2 w-2" style={{ color: ERR.accent }} />
                        ) : (
                          <svg className="w-3.5 h-3.5" viewBox="0 0 14 14">
                            <circle cx="7" cy="7" r="4.5" fill="none" stroke={groupAccent} strokeWidth="1" strokeDasharray="8 20" strokeLinecap="round" style={{ animation: "tool-spinner 1s linear infinite" }} />
                          </svg>
                        )}
                      </div>
                      <span className="text-[11px] font-medium tracking-[-0.01em]" style={{ color: `${groupAccent}cc` }}>
                        {isRetrying ? "Retrying" : `Group ${g}/${totalGroups}`} · {String(slugs)}
                      </span>
                    </div>
                    {/* Sub-tool list — show last 3 per group */}
                    {!isDone && tools.slice(-3).map((ev, i) => {
                      const toolName = stripPrefix(String(ev.tool))
                      const sub = TOOL_META[toolName] || { Icon: Wrench, label: toolName.replace(/_/g, " "), category: "other" as ToolCategory }
                      const subColors = CAT[sub.category]
                      const subDetail = getDetail(toolName, ev.input as Record<string, unknown> | undefined)
                      const isLast = i === Math.min(tools.length, 3) - 1
                      return (
                        <div key={`${g}-${ev.tool}-${i}`} className="flex items-center gap-1.5 py-0.5 ml-5" style={{ opacity: isLast ? 1 : 0.4 }}>
                          <div className="flex-none w-3.5 h-3.5 rounded flex items-center justify-center" style={{ background: `${subColors.accent}10` }}>
                            {isLast ? (
                              <svg className="w-3.5 h-3.5" viewBox="0 0 14 14">
                                <circle cx="7" cy="7" r="4.5" fill="none" stroke={subColors.accent} strokeWidth="1" strokeDasharray="8 20" strokeLinecap="round" style={{ animation: "tool-spinner 1s linear infinite" }} />
                              </svg>
                            ) : (
                              <sub.Icon className="h-2 w-2" style={{ color: `${subColors.accent}80` }} />
                            )}
                          </div>
                          <span className="text-[11px] truncate" style={{ color: isLast ? subColors.accent : `${subColors.accent}88` }}>
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

      {/* Right-side status dot */}
      <div className="flex-none">
        {isActive ? (
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: colors.accent, animation: "tool-pulse 1.5s ease-in-out infinite" }}
          />
        ) : isComplete ? (
          <div
            className="w-1.5 h-1.5 rounded-full tool-check-enter"
            style={{ background: isError ? ERR.accent : colors.accent, opacity: 0.6 }}
          />
        ) : null}
      </div>
    </div>
  )
}

/**
 * ToolCardCompact — Minimal inline display for collapsed older tools.
 *
 * @param props.name - Tool function name
 * @param props.input - Tool input parameters
 */
export function ToolCardCompact({ name, input }: { name: string; input?: Record<string, unknown> }) {
  const meta = TOOL_META[name] || { Icon: Wrench, label: name.replace(/_/g, " "), category: "other" as ToolCategory }
  const colors = CAT[meta.category]
  const detail = getDetail(name, input)

  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-foreground/30 py-0.5">
      <meta.Icon className="h-2.5 w-2.5" style={{ color: `${colors.accent}80` }} />
      <span>{meta.label}</span>
      {detail && <span className="opacity-60 truncate max-w-[150px]">{detail}</span>}
    </span>
  )
}
