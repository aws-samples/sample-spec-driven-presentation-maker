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
  retry: CAT.explore.accent,
  error: "var(--state-error)",
}

export const C = {
  fgStrong: "var(--foreground)",
  fgLabel: "var(--foreground-secondary)",
  fgMuted: "var(--foreground-muted)",
  fgDim: "var(--muted-foreground)",
  smallLabel: "var(--muted-foreground)",
  existing: "var(--agent-visual)",
  detailZone: "var(--surface-subtle)",
}

export const MONO = "var(--font-geist-mono, ui-monospace), monospace"

export function getToolMeta(tool: string) {
  const meta = TOOL_META[stripPrefix(tool)]
  return meta ?? { Icon: Wrench, label: tool, category: "other" as const }
}
