// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * EmptyState — Centered placeholder for empty list views.
 * Shows an icon, heading, description, and optional CTA button.
 *
 * @param props.icon - Lucide icon component to display
 * @param props.title - Heading text
 * @param props.description - Supporting description text
 * @param props.actionLabel - Optional CTA button label
 * @param props.onAction - Optional CTA button callback
 */

import { type LucideIcon } from "lucide-react"

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
}

export function EmptyState({ icon: Icon, title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="animate-card-in flex flex-col items-center justify-center py-20 text-center">
      <div className="w-16 h-16 rounded-2xl bg-background-raised border border-border flex items-center justify-center mb-5">
        <Icon className="h-7 w-7 text-brand-teal/25" />
      </div>
      <h2 className="text-base font-semibold tracking-[-0.02em] mb-1">{title}</h2>
      <p className="text-[13px] text-foreground-muted max-w-[260px] mb-5 leading-relaxed">
        {description}
      </p>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-[12px] font-semibold rounded-lg bg-brand-teal text-primary-foreground transition-all hover:brightness-110"
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}
