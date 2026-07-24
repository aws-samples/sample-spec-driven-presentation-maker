// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ErrorBoundary — catches render errors so one crashing component
 * doesn't take down the whole app.
 *
 * Shows a fallback with the error message and a reload action.
 * Wrap independently-recoverable regions (e.g. chat panel) separately
 * so the rest of the UI stays usable.
 *
 * @param props.label - Region name shown in the fallback (e.g. "Chat")
 */

"use client"

import { Component, type ReactNode } from "react"
import { RefreshCw, AlertTriangle } from "lucide-react"
import { useTranslations } from "next-intl"

interface ErrorBoundaryProps {
  children: ReactNode
  label?: string
}

interface ErrorBoundaryState {
  error: Error | null
}

/** Fallback UI — functional so it can use the translation hook (the boundary itself is a class). */
function ErrorFallback({ label, message, onRetry }: { label?: string; message: string; onRetry: () => void }) {
  const t = useTranslations("errorBoundary")
  return (
    <div className="flex flex-col items-center justify-center gap-3 h-full min-h-[200px] p-6 text-center">
      <AlertTriangle className="w-8 h-8 text-brand-amber" aria-hidden="true" />
      <p className="text-sm text-foreground">{t("problem", { label: label || t("thisSection") })}</p>
      <p className="text-xs text-foreground-muted max-w-md break-words">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="touch-target inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-border text-foreground hover:border-border-hover transition-colors"
      >
        <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
        {t("tryAgain")}
      </button>
    </div>
  )
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error("ErrorBoundary caught:", error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <ErrorFallback
        label={this.props.label}
        message={this.state.error.message}
        onRetry={() => this.setState({ error: null })}
      />
    )
  }
}
