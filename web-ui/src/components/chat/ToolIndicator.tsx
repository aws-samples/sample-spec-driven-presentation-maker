// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ToolIndicator — Compact status line for a tool execution.
 * Uses Lucide icons instead of emoji for a polished look.
 *
 * @param name - Tool function name
 * @param input - Tool input parameters (used to derive detail text)
 * @param isActive - Whether the tool is currently running
 */

import {
  BookOpen, List, Search, FolderPlus, Pencil, Image,
  Trash2, ArrowUpDown, FolderOpen, Copy, Globe, Wrench, Loader2,
  FileText, Download, Play, Code, LayoutTemplate, Package,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

/** Icon component and base label per tool name. */
const TOOL_META: Record<string, { Icon: LucideIcon; label: string }> = {
  // Native agent tools
  read_reference:     { Icon: BookOpen,        label: "Reading" },
  list_references:    { Icon: List,            label: "Listing patterns" },
  search_icons:       { Icon: Search,          label: "Searching icons" },
  create_deck:        { Icon: FolderPlus,      label: "Creating deck" },
  write_slide:        { Icon: Pencil,          label: "Writing slide" },
  generate_pptx:      { Icon: Download,        label: "Generating PPTX" },
  generate_preview:   { Icon: Image,           label: "Generating preview" },
  remove_slide:       { Icon: Trash2,          label: "Removing slide" },
  reorder_slides:     { Icon: ArrowUpDown,     label: "Reordering" },
  get_deck:           { Icon: FolderOpen,      label: "Loading deck" },
  search_slides:      { Icon: Search,          label: "Searching slides" },
  clone_deck:         { Icon: Copy,            label: "Cloning deck" },
  clone_slide:        { Icon: Copy,            label: "Cloning slide" },
  web_search:         { Icon: Globe,           label: "Searching" },
  web_fetch:          { Icon: FileText,        label: "Fetching page" },
  read_uploaded_file: { Icon: FileText,        label: "Reading file" },
  // MCP Server tools
  init_presentation:  { Icon: FolderPlus,      label: "Initializing deck" },
  analyze_template:   { Icon: LayoutTemplate,  label: "Analyzing template" },
  start_presentation: { Icon: Play,            label: "Starting workflow" },
  list_templates:     { Icon: LayoutTemplate,  label: "Listing templates" },
  list_styles:        { Icon: List,            label: "Listing styles" },
  read_examples:      { Icon: BookOpen,        label: "Reading example" },
  list_workflows:     { Icon: List,            label: "Listing workflows" },
  read_workflows:     { Icon: BookOpen,        label: "Reading workflow" },
  list_guides:        { Icon: List,            label: "Listing guides" },
  read_guides:        { Icon: BookOpen,        label: "Reading guide" },
  search_assets:      { Icon: Search,          label: "Searching assets" },
  list_asset_sources: { Icon: Package,         label: "Listing sources" },
  get_preview:        { Icon: Image,           label: "Getting preview" },
  run_python:         { Icon: Code,            label: "Running code" },
  code_to_slide:      { Icon: Code,            label: "Code to slide" },
  pptx_to_json:       { Icon: FileText,        label: "Converting PPTX" },
}

/**
 * Extract a short detail string from tool input for display.
 *
 * @param name - Tool name
 * @param input - Tool input object
 * @returns A short descriptive string, or empty string
 */
function getDetail(name: string, input?: Record<string, unknown>): string {
  if (!input) return ""
  const v =
    input.name || input.path || input.query || input.keyword ||
    input.slide_id || input.new_name || input.deck_id || input.template
  if (typeof v === "string" && v) return v.length > 40 ? v.slice(0, 40) + "…" : v
  return ""
}

interface ToolIndicatorProps {
  name: string
  input?: Record<string, unknown>
  isActive?: boolean
}

export function ToolIndicator({ name, input, isActive = false }: ToolIndicatorProps) {
  const meta = TOOL_META[name] || { Icon: Wrench, label: name.replace(/_/g, " ") }
  const { Icon } = meta
  const detail = getDetail(name, input)

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground py-0.5"
      role="status"
      aria-label={`${isActive ? "Running" : "Completed"}: ${meta.label}${detail ? ` — ${detail}` : ""}`}
    >
      {isActive ? (
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/60" />
      ) : (
        <Icon className="h-3 w-3 text-muted-foreground/60" />
      )}
      <span>{meta.label}</span>
      {detail && <span className="text-muted-foreground/50 truncate max-w-[200px]">{detail}</span>}
    </span>
  )
}
