// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ComposeCard — Tool card for compose_slides, showing parallel composer agents.
 *
 * Design principles:
 *   - ToolCard-consistent outer shell (produce violet bg + border)
 *   - Two-line always-visible AgentCard (identity / current activity)
 *   - Inline accordion (chevron toggle) for instruction + full activity history
 *   - Activity timeline prioritizes "what the agent did" (icons + category color)
 *   - Minimal motion: breathing for active/retry only, no 3D tilt / hue offsets
 */

"use client"

import { useState, useMemo } from "react"
import { Package, Check, AlertCircle, RefreshCw, X } from "lucide-react"
import { parseComposeState, type ComposeState } from "./parseComposeState"
import { CAT } from "../toolPalette"
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
  const [stopping, setStopping] = useState(false)
  const state: ComposeState = useMemo(
    () => parseComposeState(streamMessages, input),
    [streamMessages, input],
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

  const shellBg = hasError
    ? "oklch(0.65 0.2 25 / 6%)"
    : stopping && isActive
    ? `${STATE.retry}0f`
    : CAT.produce.bg
  const shellBorder = hasError
    ? "oklch(0.65 0.2 25 / 18%)"
    : stopping && isActive
    ? `${STATE.retry}40`
    : CAT.produce.border

  return (
    <section
      aria-label="Composing slides"
      className="tool-card-enter relative rounded-xl"
      style={{
        background: shellBg,
        boxShadow: `inset 0 0 0 1px ${shellBorder}`,
      }}
    >
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
      <div className="px-3 pb-3 flex flex-col gap-2">
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
        {state.doneGroupCount} of {state.totalGroups} agents completed
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
  const hasAgents = state.totalGroups > 0
  const isFinished = isDone || (hasError && !isActive) || isStopped
  const isStopping = stopping && isActive
  const label = isStopping
    ? "Stopping — finalizing partial results…"
    : isStopped
    ? doneSlides > 0
      ? `Stopped · ${doneSlides} of ${totalSlides} slides composed`
      : "Stopped"
    : hasError && !isActive
    ? doneSlides > 0
      ? `Composed ${doneSlides} of ${totalSlides} slides — some failed`
      : "Failed to compose slides"
    : isDone
    ? `Composed ${totalSlides || state.totalGroups} slides`
    : hasAgents
    ? `Composing ${totalSlides} slides · ${state.totalGroups} agents in parallel`
    : state.statusMessage || "Preparing…"

  const accent = hasError
    ? STATE.error
    : isStopping
    ? STATE.retry
    : isStopped
    ? C.fgMuted
    : CAT.produce.accent

  return (
    <header className="flex items-center gap-2.5 px-3 pt-3 pb-2">
      <div
        className="flex-none w-7 h-7 rounded-lg flex items-center justify-center relative"
        style={{ background: `${accent}18` }}
      >
        {isActive && !isFinished ? (
          <svg className="absolute inset-0 w-7 h-7" viewBox="0 0 28 28">
            <circle
              cx="14" cy="14" r="12"
              fill="none" stroke={accent} strokeWidth="1.5"
              strokeDasharray="20 56" strokeLinecap="round"
              style={{ animation: "tool-spinner 1.2s linear infinite" }}
            />
          </svg>
        ) : null}
        {hasError && !isActive ? (
          <AlertCircle className="h-3.5 w-3.5" style={{ color: accent }} />
        ) : isDone ? (
          <Check className="h-3.5 w-3.5" style={{ color: accent }} />
        ) : (
          <Package className="h-3.5 w-3.5" style={{ color: accent }} />
        )}
      </div>
      <span
        className="flex-1 min-w-0 text-[12.5px] font-medium tracking-[-0.01em] truncate"
        style={{ color: accent }}
        aria-live="polite"
      >
        {label}
      </span>
      {rushedCount > 0 && !isStopping && (
        <span
          className="flex-none inline-flex items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-medium"
          style={{ color: STATE.retry, background: `${STATE.retry}14`, fontFamily: MONO }}
          title={`${rushedCount} composer${rushedCount > 1 ? "s" : ""} hit the time budget — rough drafts may need another pass`}
        >
          {rushedCount} rushed
        </span>
      )}
      {isStopping ? (
        <span
          className="flex-none inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] font-medium"
          style={{ color: accent, background: `${accent}14` }}
          aria-label="Cancel requested, stopping"
        >
          <RefreshCw
            className="h-3 w-3"
            style={{ animation: "tool-spinner 1.2s linear infinite" }}
          />
          Stopping…
        </span>
      ) : canCancel ? (
        <button
          type="button"
          onClick={onCancel}
          className="flex-none inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] font-medium text-foreground/70 hover:text-foreground/95 hover:bg-white/5 transition-colors"
          aria-label="Cancel compose slides"
        >
          <X className="h-3 w-3" />
          Cancel
        </button>
      ) : null}
    </header>
  )
}
