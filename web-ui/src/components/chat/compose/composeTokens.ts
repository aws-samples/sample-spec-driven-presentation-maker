// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Shared tokens/helpers for compose_slides UI. */

import { Wrench } from "lucide-react"
import { TOOL_META } from "../ToolCard"
import { stripPrefix } from "./activityLabel"

export const STATE = {
  retry: "var(--agent-data)",
  error: "var(--state-error)",
}

export const C = {
  fgStrong: "var(--foreground)",
  fgLabel: "var(--foreground-secondary)",
  fgMuted: "var(--foreground-muted)",
  fgDim: "var(--muted-foreground)",
  smallLabel: "var(--muted-foreground)",
}

export const MONO = "var(--font-geist-mono), ui-monospace, monospace"

export function getToolMeta(tool: string) {
  const meta = TOOL_META[stripPrefix(tool)]
  return meta ?? { Icon: Wrench, label: tool, category: "other" as const }
}
