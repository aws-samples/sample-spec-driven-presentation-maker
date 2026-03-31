// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * DeleteDeckModal — Confirmation dialog for deck deletion.
 *
 * Dark glass modal consistent with the editorial design system.
 * Shows deck name and warns about 30-day permanent deletion.
 *
 * @param props.deckName - Name of the deck to delete
 * @param props.onConfirm - Callback when user confirms deletion
 * @param props.onCancel - Callback when user cancels
 */

"use client"

import { Trash2 } from "lucide-react"

interface DeleteDeckModalProps {
  deckName: string
  onConfirm: () => void
  onCancel: () => void
}

export function DeleteDeckModal({ deckName, onConfirm, onCancel }: DeleteDeckModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div
        className="w-full max-w-sm mx-4 p-5 rounded-xl border border-white/[0.08] shadow-[0_8px_32px_oklch(0_0_0/50%)]"
        style={{ background: "oklch(0.14 0.005 260 / 95%)", backdropFilter: "blur(16px)" }}
      >
        <div className="flex items-center gap-3 mb-3">
          <div className="p-2 rounded-lg bg-red-500/10">
            <Trash2 className="h-5 w-5 text-red-400" />
          </div>
          <h3 className="text-sm font-semibold">Delete this deck?</h3>
        </div>
        <p className="text-xs text-foreground-muted mb-1">
          <span className="font-medium text-foreground">{deckName}</span> will be permanently deleted after 30 days.
        </p>
        <p className="text-xs text-foreground-muted mb-4">This action cannot be undone.</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs font-medium rounded-lg text-foreground-secondary hover:bg-background-hover transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-red-600 text-white hover:bg-red-500 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}
