// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Shared color palette for tool categories.
 * Split from ToolCard.tsx to avoid circular imports with ComposeCard.
 */

export type ToolCategory = "build" | "explore" | "produce" | "compute" | "hearing" | "other"

/**
 * Tool categories map to the same five people shown on the slide stage.
 * Color answers “who is working”; shape and copy communicate state and content.
 */
const agent = (token: string, alpha = { bg: 6, glow: 12, border: 18 }) => ({
  accent: `var(${token})`,
  bg: `color-mix(in oklch, var(${token}) ${alpha.bg}%, transparent)`,
  glow: `color-mix(in oklch, var(${token}) ${alpha.glow}%, transparent)`,
  border: `color-mix(in oklch, var(${token}) ${alpha.border}%, transparent)`,
})

export const CAT: Record<ToolCategory, { accent: string; bg: string; glow: string; border: string }> = {
  build: agent("--agent-content"),
  explore: agent("--agent-data"),
  produce: agent("--agent-visual"),
  compute: agent("--agent-layout"),
  hearing: agent("--agent-decorator"),
  other: agent("--agent-neutral", { bg: 4, glow: 8, border: 12 }),
}
