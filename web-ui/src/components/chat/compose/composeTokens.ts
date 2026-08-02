// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Shared design tokens and helpers for the compose_slides card family
 * (ComposeCard / AgentCard / StopSummary).
 *
 * Agent identity mapping: group i (1-based) maps cyclically to one of five
 * agent identities (i mod 5). This ensures the same agent color appears on
 * the slide stage cursor and the corresponding ComposeCard row.
 */

import { Wrench } from "lucide-react"
import { TOOL_META } from "../ToolCard"
import { stripPrefix } from "./activityLabel"

/** The five agent identities in cycle order (0-indexed). */
export const AGENT_IDENTITIES = [
  { token: "--agent-layout", name: "Layout" },
  { token: "--agent-content", name: "Content" },
  { token: "--agent-visual", name: "Visual" },
  { token: "--agent-data", name: "Data" },
  { token: "--agent-decorator", name: "Decorator" },
] as const

export type AgentIdentity = (typeof AGENT_IDENTITIES)[number]

/**
 * Map a 1-based group index to one of five agent identities cyclically.
 * group 1 → Layout, group 2 → Content, ..., group 6 → Layout, etc.
 */
export function getAgentIdentity(groupIndex: number): AgentIdentity {
  return AGENT_IDENTITIES[(groupIndex - 1) % 5]
}

/** Get the CSS variable value string for an agent identity. */
export function agentColor(identity: AgentIdentity): string {
  return `var(${identity.token})`
}

export const STATE = {
  working: "var(--agent-visual)",
  retry: "var(--agent-data)",
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

export const MONO = "var(--font-geist-mono), ui-monospace, monospace"

export function getToolMeta(tool: string) {
  const meta = TOOL_META[stripPrefix(tool)]
  return meta ?? { Icon: Wrench, label: tool, category: "other" as const }
}
