// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

/**
 * ConfirmDialog — Notion/Slack-quality confirmation modal.
 *
 * Built on Radix AlertDialog for accessibility (focus trap, aria, Escape).
 * Supports destructive and default variants.
 */

import * as React from "react"
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog"
import { cn } from "@/lib/utils"

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  variant?: "destructive" | "default"
  onConfirm: () => void
  loading?: boolean
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  loading = false,
}: ConfirmDialogProps) {
  return (
    <AlertDialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-black/70 backdrop-blur-sm",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
            "duration-200",
          )}
        />
        <AlertDialogPrimitive.Content
          className={cn(
            "fixed top-[50%] left-[50%] z-50 translate-x-[-50%] translate-y-[-50%]",
            "w-full max-w-[384px] mx-4 p-6 rounded-xl",
            "bg-[oklch(0.16_0.005_260)] border border-white/[0.08]",
            "shadow-[0_0_0_1px_oklch(1_0_0/0.04),0_8px_24px_oklch(0_0_0/0.4),0_2px_8px_oklch(0_0_0/0.3)]",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
            "data-[state=open]:zoom-in-[0.97] data-[state=closed]:zoom-out-[0.97]",
            "duration-200",
          )}
        >
          <AlertDialogPrimitive.Title className="text-sm font-semibold text-foreground mb-2">
            {title}
          </AlertDialogPrimitive.Title>
          <AlertDialogPrimitive.Description className="text-sm text-foreground-muted leading-relaxed mb-5">
            {description}
          </AlertDialogPrimitive.Description>
          <div className="flex justify-end gap-2">
            <AlertDialogPrimitive.Cancel
              className={cn(
                "px-3 py-1.5 text-sm rounded-lg transition-colors",
                "border border-white/[0.08] text-foreground-secondary",
                "hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
              )}
            >
              {cancelLabel}
            </AlertDialogPrimitive.Cancel>
            <AlertDialogPrimitive.Action
              onClick={onConfirm}
              disabled={loading}
              className={cn(
                "px-3 py-1.5 text-sm font-medium rounded-lg transition-colors",
                "focus-visible:outline-none focus-visible:ring-2",
                "disabled:opacity-50 disabled:pointer-events-none",
                variant === "destructive" && [
                  "bg-red-500/15 text-red-400 border border-red-500/20",
                  "hover:bg-red-500/25",
                  "focus-visible:ring-red-500/30",
                ],
                variant === "default" && [
                  "bg-white/10 text-foreground border border-white/[0.12]",
                  "hover:bg-white/[0.14]",
                  "focus-visible:ring-white/20",
                ],
              )}
            >
              {loading ? (
                <span className="flex items-center gap-1.5">
                  <span className="h-3 w-3 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                  {confirmLabel}
                </span>
              ) : confirmLabel}
            </AlertDialogPrimitive.Action>
          </div>
        </AlertDialogPrimitive.Content>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  )
}
