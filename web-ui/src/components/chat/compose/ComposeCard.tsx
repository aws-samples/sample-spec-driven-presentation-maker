// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ComposeCard v2 — "Curtain rises" design.
 *
 * Achromatic shell with a 2px team-gradient curtain line at top.
 * Interior uses the same work-ledger grammar as ToolCard.
 * Each group i maps to one of five agent identities cyclically (i mod 5).
 *
 * Preserves all real behavior: error auto-expand, retry/rushed badges,
 * stop button, n/m progress, StopSummary, aria-expanded, status semantics.
 */

"use client"

import { useState, useMemo } from "react"
import { useTranslations } from "next-intl"
import { Check, AlertCircle, RefreshCw, X } from "lucide-react"
import { parseComposeState, type ComposeState } from "./parseComposeState"
import { stopComposeSlides } from "@/services/agentCoreService"
import { STATE, C, MONO } from "./composeTokens"
import { AgentCard } from "./AgentCard"
import { StopSummary } from "./StopSummary"

// --- Main -------------------------------------------------------------------

interface ComposeCardProps {
  input?: Record<string, unknown>
  status?: "success" | "error"
  result?: Record<string, unknown> | string
  isActive: boolean
  streamMessages?: Record<string, unknown>[]
  deckSlugs?: string[]
  toolUseId?: string
  sessionId?: string
  /** Cognito Access Token — the AgentCore JWT authorizer matches client_id against the access token, not the id token. */
  accessToken?: string
}

export function ComposeCard({ input, status, result, isActive, streamMessages = [], deckSlugs = [], toolUseId, sessionId, accessToken }: ComposeCardProps) {
  const t = useTranslations("compose")
  const [stopping, setStopping] = useState(false)
  const state: ComposeState = useMemo(
    () => parseComposeState(streamMessages, input, t),
    [streamMessages, input, t],
  )

  // Parse the final report (the tool's last yield = JSON string). Gives us
  // `stopped`, `notice`, and per-group `summaries` for the soft-stop UI.
  const report = useMemo(() => {
    if (!result) return null
    try {
      const raw = typeof result === "string" ? result : JSON.stringify(result)
      const obj = typeof result === "object" && result !== null ? result as Record<string, unknown> : JSON.parse(raw)
      return obj as { stopped?: boolean; notice?: string; summaries?: Record<string, string>; stopped_at?: string }
    } catch {
      return null
    }
  }, [result])

  const hasError = status === "error" || state.agents.some((a) => a.status === "error")
  // Stopped: either a hard-stop (tool result never arrived — status undefined)
  // or a soft-stop (compose_slides returned normally with `stopped: true`).
  const isSoftStopped = !!report?.stopped
  const isHardStopped = !isActive && !hasError && !status && state.agents.length > 0
  const isStopped = isHardStopped || isSoftStopped
  const isDone = !isActive && !isStopped && !hasError && (status === "success" || state.phase === "done")
  const doneSlides = state.agents.filter((a) => a.status === "done").reduce((s, a) => s + a.slugs.length, 0)
  const rushedCount = state.agents.filter((a) => a.budgetReached).length

  const existingSlugs = new Set(deckSlugs)
  const totalSlides = state.agents.reduce((sum, a) => sum + a.slugs.length, 0)

  return (
    <section
      aria-label={t("composingAria")}
      className="compose-card tool-card-enter relative rounded-xl overflow-hidden"
      style={{
        background: hasError
          ? "color-mix(in oklch, var(--state-error) 4%, var(--surface-subtle))"
          : "var(--surface-subtle)",
        boxShadow: hasError
          ? "inset 0 0 0 1px color-mix(in oklch, var(--state-error) 15%, transparent)"
          : "inset 0 0 0 1px var(--border)",
      }}
    >
      {/* 2px team-gradient curtain line at top */}
      <div
        className="compose-curtain absolute inset-x-0 top-0 h-0.5"
        style={{ background: "var(--team-gradient)" }}
        aria-hidden="true"
      />

      <Header
        state={state}
        isDone={isDone}
        isStopped={isStopped}
        hasError={hasError}
        totalSlides={totalSlides}
        doneSlides={doneSlides}
        rushedCount={rushedCount}
        isActive={isActive}
        canCancel={isActive && !stopping && !!(toolUseId && sessionId && accessToken)}
        onCancel={async () => {
          if (!toolUseId || !sessionId || !accessToken) return
          setStopping(true)
          await stopComposeSlides(sessionId, toolUseId, accessToken)
        }}
        stopping={stopping}
      />
      <div className="px-3 pb-3 flex flex-col gap-0.5">
        {state.agents.map((agent, i) => (
          <AgentCard
            key={agent.groupIndex}
            agent={agent}
            existingSlugs={existingSlugs}
            indexDelay={i}
            parentActive={isActive}
            parentStopped={isStopped}
            parentStopping={stopping && isActive}
          />
        ))}
      </div>
      {isSoftStopped && (report?.notice || report?.summaries) && (
        <StopSummary notice={report.notice} summaries={report.summaries} />
      )}
      <span className="sr-only" aria-live="polite">
        {t("srProgress", { done: state.doneGroupCount, total: state.totalGroups })}
      </span>
    </section>
  )
}

// --- Header -----------------------------------------------------------------

function Header({
  state, isDone, isStopped, hasError, totalSlides, doneSlides, rushedCount, isActive,
  canCancel, onCancel, stopping,
}: {
  state: ComposeState
  isDone: boolean
  isStopped: boolean
  hasError: boolean
  totalSlides: number
  doneSlides: number
  rushedCount: number
  isActive: boolean
  canCancel: boolean
  onCancel: () => void
  stopping: boolean
}) {
  const t = useTranslations("compose")
  const hasAgents = state.totalGroups > 0
  const isFinished = isDone || (hasError && !isActive) || isStopped
  const isStopping = stopping && isActive
  const label = isStopping
    ? t("stopping")
    : isStopped
    ? doneSlides > 0
      ? t("stoppedPartial", { done: doneSlides, total: totalSlides })
      : t("stopped")
    : hasError && !isActive
    ? doneSlides > 0
      ? t("composedPartialFailed", { done: doneSlides, total: totalSlides })
      : t("failed")
    : isDone
    ? t("composed", { count: totalSlides || state.totalGroups })
    : hasAgents
    ? t("composing", { slides: totalSlides, agents: state.totalGroups })
    : state.statusMessage || t("preparing")

  const accent = hasError
    ? STATE.error
    : isStopping
    ? STATE.retry
    : isStopped
    ? C.fgMuted
    : C.fgLabel

  return (
    <header className="flex items-center gap-2.5 px-3 pt-3.5 pb-2">
      <div
        className="flex-none w-6 h-6 rounded-md flex items-center justify-center relative"
        style={{ background: `color-mix(in oklch, ${hasError ? STATE.error : "var(--foreground)"} 8%, transparent)` }}
      >
        {isActive && !isFinished ? (
          <svg className="absolute inset-0 w-6 h-6" viewBox="0 0 24 24">
            <circle
              cx="12" cy="12" r="9.5"
              fill="none" stroke={hasError ? STATE.error : "var(--foreground-muted)"} strokeWidth="1.5"
              strokeDasharray="16 44" strokeLinecap="round"
              style={{ animation: "tool-spinner 1.2s linear infinite" }}
            />
          </svg>
        ) : null}
        {hasError && !isActive ? (
          <AlertCircle className="h-3.5 w-3.5" style={{ color: STATE.error }} />
        ) : isDone ? (
          <Check className="h-3.5 w-3.5" style={{ color: "var(--foreground-secondary)" }} />
        ) : null}
      </div>
      <span
        className="flex-1 min-w-0 text-xs font-medium tracking-[-0.01em] truncate"
        style={{ color: accent }}
        aria-live="polite"
      >
        {label}
      </span>
      {hasAgents && !isStopping && (
        <span
          className="flex-none text-[11px] tabular-nums"
          style={{ color: C.fgMuted, fontFamily: MONO }}
        >
          {state.doneGroupCount}/{state.totalGroups}
        </span>
      )}
      {rushedCount > 0 && !isStopping && (
        <span
          className="flex-none inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium"
          style={{ color: STATE.retry, background: `color-mix(in oklch, ${STATE.retry} 10%, transparent)`, fontFamily: MONO }}
          title={t("rushedBadgeTitle", { count: rushedCount })}
        >
          {t("rushedBadge", { count: rushedCount })}
        </span>
      )}
      {isStopping ? (
        <span
          className="flex-none inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium"
          style={{ color: STATE.retry, background: `color-mix(in oklch, ${STATE.retry} 10%, transparent)` }}
          aria-label={t("cancelRequestedAria")}
        >
          <RefreshCw
            className="h-3 w-3"
            style={{ animation: "tool-spinner 1.2s linear infinite" }}
          />
          {t("stoppingShort")}
        </span>
      ) : canCancel ? (
        <button
          type="button"
          onClick={onCancel}
          className="flex-none inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-foreground/70 hover:text-foreground/95 hover:bg-foreground/5 transition-colors"
          aria-label={t("cancelAria")}
        >
          <X className="h-3 w-3" />
          {t("cancel")}
        </button>
      ) : null}
    </header>
  )
}
