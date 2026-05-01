// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Shared color palette for tool categories.
 * Split from ToolCard.tsx to avoid circular imports with ComposeCard.
 */

export type ToolCategory = "build" | "explore" | "produce" | "compute" | "hearing" | "other"

/** Accent palette per category — oklch for perceptual uniformity. */
export const CAT: Record<ToolCategory, { accent: string; bg: string; glow: string; border: string }> = {
  build:   { accent: "oklch(0.75 0.14 185)", bg: "oklch(0.75 0.14 185 / 6%)",  glow: "oklch(0.75 0.14 185 / 12%)", border: "oklch(0.75 0.14 185 / 18%)" },
  explore: { accent: "oklch(0.80 0.14 80)",  bg: "oklch(0.80 0.14 80 / 6%)",   glow: "oklch(0.80 0.14 80 / 12%)",  border: "oklch(0.80 0.14 80 / 18%)" },
  produce: { accent: "oklch(0.72 0.16 300)", bg: "oklch(0.72 0.16 300 / 6%)",  glow: "oklch(0.72 0.16 300 / 12%)", border: "oklch(0.72 0.16 300 / 18%)" },
  compute: { accent: "oklch(0.78 0.12 220)", bg: "oklch(0.78 0.12 220 / 6%)",  glow: "oklch(0.78 0.12 220 / 12%)", border: "oklch(0.78 0.12 220 / 18%)" },
  hearing: { accent: "oklch(0.74 0.16 330)", bg: "oklch(0.74 0.16 330 / 6%)",  glow: "oklch(0.74 0.16 330 / 12%)", border: "oklch(0.74 0.16 330 / 18%)" },
  other:   { accent: "oklch(0.55 0 0)",      bg: "oklch(0.55 0 0 / 4%)",       glow: "oklch(0.55 0 0 / 8%)",       border: "oklch(0.55 0 0 / 12%)" },
}
