// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SelectionBar — Floating action bar for the deck list's selection mode.
 *
 * Pinned to the bottom of the viewport; announces the selection count and
 * offers Select all / Delete / Cancel. While a bulk delete runs it shows
 * progress and disables the actions.
 *
 * @param props.count - Number of selected decks
 * @param props.total - Number of selectable (visible) decks
 * @param props.progress - Bulk-delete progress; when set, actions are disabled
 * @param props.onSelectAll - Select every visible deck
 * @param props.onDelete - Open the bulk-delete confirmation
 * @param props.onCancel - Leave selection mode
 */

"use client"

import { CheckSquare, Trash2, X } from "lucide-react"
import { useTranslations } from "next-intl"

interface SelectionBarProps {
  count: number
  total: number
  progress: { done: number; total: number } | null
  onSelectAll: () => void
  onDelete: () => void
  onCancel: () => void
}

export function SelectionBar({ count, total, progress, onSelectAll, onDelete, onCancel }: SelectionBarProps) {
  const t = useTranslations("deckList")
  const busy = progress !== null
  const allSelected = total > 0 && count >= total

  return (
    <div
      role="toolbar"
      aria-label={t("selectionToolbar")}
      className="animate-card-in fixed left-1/2 z-40 -translate-x-1/2 flex items-center gap-1 rounded-full border border-border bg-popover/95 backdrop-blur-xl px-2 py-1 shadow-[var(--shadow-lift)] motion-reduce:animate-none"
      style={{ bottom: "calc(1.5rem + env(safe-area-inset-bottom, 0px))" }}
    >
      <span
        className="px-3 text-sm font-semibold tabular-nums text-foreground whitespace-nowrap"
        aria-live="polite"
        aria-atomic="true"
      >
        {busy
          ? t("deletingProgress", { done: progress.done, total: progress.total })
          : t("selectedCount", { count })}
      </span>

      <span className="h-5 w-px bg-border" aria-hidden="true" />

      <button
        type="button"
        onClick={onSelectAll}
        disabled={busy || allSelected}
        className="touch-target inline-flex items-center gap-1.5 rounded-full px-3 text-sm font-medium text-foreground-secondary hover:bg-foreground/[6%] hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
      >
        <CheckSquare className="h-3.5 w-3.5" aria-hidden="true" />
        {t("selectAll", { total })}
      </button>

      <button
        type="button"
        onClick={onDelete}
        disabled={busy || count === 0}
        className="touch-target inline-flex items-center gap-1.5 rounded-full px-3 text-sm font-semibold text-state-error hover:bg-state-error/10 disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
      >
        {busy ? (
          <span
            className="h-3.5 w-3.5 rounded-full border border-current border-t-transparent"
            style={{ animation: "tool-spinner 1.2s linear infinite" }}
            aria-hidden="true"
          />
        ) : (
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {t("deleteSelected")}
      </button>

      <button
        type="button"
        onClick={onCancel}
        disabled={busy}
        aria-label={t("cancelSelection")}
        className="touch-target inline-flex items-center justify-center rounded-full text-foreground-muted hover:bg-foreground/[6%] hover:text-foreground disabled:opacity-40 transition-colors"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  )
}
