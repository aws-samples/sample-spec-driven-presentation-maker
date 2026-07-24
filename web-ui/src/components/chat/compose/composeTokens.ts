// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Shared design tokens and helpers for the compose_slides card family
 * (ComposeCard / AgentCard / StopSummary).
 */

import { Wrench } from "lucide-react"
import { CAT } from "../toolPalette"
import { TOOL_META } from "../ToolCard"
import { stripPrefix } from "./activityLabel"

export const STATE = {
  working: CAT.produce.accent,
  retry: CAT.explore.accent, // amber
  error: "oklch(0.65 0.2 25)",
}

export const C = {
  fgStrong: "oklch(0.92 0.005 85)",
  fgLabel: "oklch(0.82 0 0)",
  fgMuted: "oklch(0.48 0 0)",
  fgDim: "oklch(0.55 0 0)",
  smallLabel: "oklch(0.52 0 0)",
  existing: "oklch(0.82 0.10 300)",
  detailZone: "oklch(1 0 0 / 3%)",
}

export const MONO = "var(--font-geist-mono, ui-monospace), monospace"

export function getToolMeta(tool: string) {
  const meta = TOOL_META[stripPrefix(tool)]
  return meta ?? { Icon: Wrench, label: tool, category: "other" as const }
}
