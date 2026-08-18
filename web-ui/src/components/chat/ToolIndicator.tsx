// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ToolIndicator — Compact status line for a tool execution in the ledger.
 * Shows a left marker dot and label, consistent with the ledger row language.
 *
 * @param name - Tool function name
 * @param input - Tool input parameters (used to derive detail text)
 * @param isActive - Whether the tool is currently running
 */

import { Wrench } from "lucide-react"
import { useTranslations } from "next-intl"
import { TOOL_META, stripPrefix } from "./ToolCard"
import { CAT } from "./toolPalette"

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
  const t = useTranslations("tools")
  const meta = TOOL_META[stripPrefix(name)] || { Icon: Wrench, label: name.replace(/_/g, " "), category: "other" }
  const category = "category" in meta ? meta.category : "other"
  const colors = CAT[category as keyof typeof CAT] || CAT.other
  // Known tools resolve via messages; unknown tools fall back to the derived label
  const label = t.has(stripPrefix(name)) ? t(stripPrefix(name)) : meta.label
  const detail = getDetail(name, input)

  return (
    <span
      className="ledger-indicator inline-flex items-center gap-1.5 text-xs text-muted-foreground py-0.5"
      role="status"
      aria-label={`${isActive ? t("running") : t("completed")}: ${label}${detail ? ` — ${detail}` : ""}`}
    >
      {/* Left marker: active = pulsing dot, done = muted dot */}
      {isActive ? (
        <span
          className="flex-none w-1.5 h-1.5 rounded-full"
          style={{ background: colors.accent, animation: "tool-pulse 1.5s ease-in-out infinite" }}
          aria-hidden="true"
        />
      ) : (
        <span
          className="flex-none w-1.5 h-1.5 rounded-full"
          style={{ background: colors.accent, opacity: 0.4 }}
          aria-hidden="true"
        />
      )}
      <span>{label}</span>
      {detail && <span className="text-muted-foreground/50 truncate max-w-[200px]">{detail}</span>}
    </span>
  )
}
