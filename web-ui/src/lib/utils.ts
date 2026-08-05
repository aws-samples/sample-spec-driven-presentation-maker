// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const DATE_LABELS = {
  en: { today: "Today", yesterday: "Yesterday", daysAgo: (n: number) => `${n}d ago`, locale: "en-US" },
  ja: { today: "今日", yesterday: "昨日", daysAgo: (n: number) => `${n}日前`, locale: "ja-JP" },
} as const

/**
 * Format an ISO timestamp as a relative date string.
 *
 * @param iso - ISO 8601 timestamp
 * @param locale - Display locale (default "en")
 * @returns Human-readable relative date (e.g. "Today", "3d ago", "Feb 14")
 */
export function formatDate(iso: string, locale: "en" | "ja" = "en"): string {
  if (!iso) return ""
  const l = DATE_LABELS[locale]
  const d = new Date(iso)
  const now = new Date()
  const diff = Math.floor((now.getTime() - d.getTime()) / 86400000)
  if (diff === 0) return l.today
  if (diff === 1) return l.yesterday
  if (diff < 7) return l.daysAgo(diff)
  return d.toLocaleDateString(l.locale, { month: "short", day: "numeric" })
}

/**
 * Generate a deterministic mesh gradient from a deck ID.
 * Uses the five agent hues (262/170/300/75/330) to keep the mesh
 * derived from team colors. Preserves slide artwork colors untouched.
 *
 * @param id - Deck identifier used as seed
 * @returns CSS background value with layered gradients
 */
export function meshGradient(id: string): string {
  const agentHues = [262, 170, 300, 75, 330]
  // Better hash: incorporate all characters
  let hash = 0
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash + id.charCodeAt(i)) | 0
  }
  hash = Math.abs(hash)
  const h1 = agentHues[hash % 5]
  const h2 = agentHues[((hash >>> 4) + 1) % 5]
  const h3 = agentHues[((hash >>> 8) + 2) % 5]
  return [
    `radial-gradient(ellipse at 20% 20%, oklch(0.28 0.04 ${h1}) 0%, transparent 50%)`,
    `radial-gradient(ellipse at 80% 80%, oklch(0.22 0.03 ${h2}) 0%, transparent 50%)`,
    `radial-gradient(ellipse at 60% 30%, oklch(0.18 0.02 ${h3}) 0%, transparent 60%)`,
    `linear-gradient(135deg, oklch(0.14 0.01 ${h1}) 0%, oklch(0.11 0.005 260) 100%)`,
  ].join(", ")
}
