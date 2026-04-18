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
import { Package, ChevronRight, Check, AlertCircle, RefreshCw, Sparkles, Wrench, X } from "lucide-react"
import { parseComposeState, type AgentState, type ComposeState } from "./parseComposeState"
import { stripPrefix } from "./activityLabel"
import { CAT } from "../toolPalette"
import { stopComposeSlides } from "@/services/agentCoreService"
import { TOOL_META } from "../ToolCard"

// --- Tokens -----------------------------------------------------------------

const STATE = {
  working: CAT.produce.accent,
  retry: CAT.explore.accent, // amber
  error: "oklch(0.65 0.2 25)",
}

const C = {
  fgStrong: "oklch(0.92 0.005 85)",
  fgLabel: "oklch(0.82 0 0)",
  fgMuted: "oklch(0.48 0 0)",
  fgDim: "oklch(0.55 0 0)",
  smallLabel: "oklch(0.52 0 0)",
  existing: "oklch(0.82 0.10 300)",
  detailZone: "oklch(1 0 0 / 3%)",
}

const MONO = "var(--font-geist-mono, ui-monospace), monospace"

function getToolMeta(tool: string) {
  const meta = TOOL_META[stripPrefix(tool)]
  return meta ?? { Icon: Wrench, label: tool, category: "other" as const }
}

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
  idToken?: string
}

export function ComposeCard({ input, status, result, isActive, streamMessages = [], deckSlugs = [], toolUseId, sessionId, idToken }: ComposeCardProps) {
  const [stopping, setStopping] = useState(false)
  const state: ComposeState = useMemo(
    () => parseComposeState(streamMessages, input),
    [streamMessages, input],
  )

  const hasError = status === "error" || state.agents.some((a) => a.status === "error")
  // Stopped: no terminal tool result was recorded (status undefined). Covers
  // both live stop (StopRuntimeSession before final yield) and history
  // restore of a session that was interrupted mid-tool (toolUse persisted in
  // Memory without a matching toolResult).
  const isStopped = !isActive && !hasError && !status && state.agents.length > 0
  const isDone = !isActive && !isStopped && !hasError && (status === "success" || state.phase === "done")
  const doneSlides = state.agents.filter((a) => a.status === "done").reduce((s, a) => s + a.slugs.length, 0)

  const existingSlugs = new Set(deckSlugs)
  const totalSlides = state.agents.reduce((sum, a) => sum + a.slugs.length, 0)

  const shellBg = hasError ? "oklch(0.65 0.2 25 / 6%)" : CAT.produce.bg
  const shellBorder = hasError ? "oklch(0.65 0.2 25 / 18%)" : CAT.produce.border

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
        isActive={isActive}
        canCancel={isActive && !stopping && !!(toolUseId && sessionId && idToken)}
        onCancel={async () => {
          if (!toolUseId || !sessionId || !idToken) return
          setStopping(true)
          await stopComposeSlides(sessionId, toolUseId, idToken)
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
            parentStopped={isStopped}
          />
        ))}
      </div>
      <span className="sr-only" aria-live="polite">
        {state.doneGroupCount} of {state.totalGroups} agents completed
      </span>
    </section>
  )
}

// --- Header -----------------------------------------------------------------

function Header({
  state, isDone, isStopped, hasError, totalSlides, doneSlides, isActive,
  canCancel, onCancel, stopping,
}: {
  state: ComposeState
  isDone: boolean
  isStopped: boolean
  hasError: boolean
  totalSlides: number
  doneSlides: number
  isActive: boolean
  canCancel: boolean
  onCancel: () => void
  stopping: boolean
}) {
  const hasAgents = state.totalGroups > 0
  const isFinished = isDone || (hasError && !isActive) || isStopped
  const label = stopping && isActive
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

  const accent = hasError ? STATE.error : isStopped ? C.fgMuted : CAT.produce.accent

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
      >
        {label}
      </span>
      {canCancel ? (
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

// --- AgentCard --------------------------------------------------------------

interface AgentCardProps {
  agent: AgentState
  existingSlugs: Set<string>
  indexDelay: number
  parentStopped: boolean
}

function AgentCard({ agent, existingSlugs, indexDelay, parentStopped }: AgentCardProps) {
  const [userToggled, setUserToggled] = useState<boolean | null>(null)
  // Default expansion: error → expanded, otherwise collapsed. User toggle overrides.
  const expanded = userToggled ?? agent.status === "error"

  // Stopped: parent card determined this compose was stopped and this agent
  // never reached a terminal state. Treat as done-but-incomplete; suppress spinners.
  const isStopped = parentStopped && agent.status !== "done" && agent.status !== "error"
  const isWorking = agent.status === "working" && !isStopped
  const isRetrying = agent.status === "retrying" && !isStopped
  const isDone = agent.status === "done"
  const isError = agent.status === "error"
  const isStarting = agent.status === "starting" && !isStopped

  const latestActivity = agent.activity.length
    ? agent.activity[agent.activity.length - 1]
    : null

  const detailId = `compose-agent-${agent.groupIndex}-detail`

  // State dot/icon
  const markerColor = isError ? STATE.error : isRetrying ? STATE.retry : STATE.working

  return (
    <div
      className="relative rounded-lg"
      style={{
        background: "oklch(0.14 0.005 280 / 50%)",
        boxShadow: "inset 0 0 0 1px oklch(1 0 0 / 5%)",
        animation: `compose-card-enter 500ms cubic-bezier(0.22, 1, 0.36, 1) ${indexDelay * 80}ms both`,
      }}
    >
      {/* Row 1 */}
      <div className="flex items-center gap-2.5 px-3 py-2">
        {/* State marker */}
        {isDone ? (
          <Check
            aria-hidden="true"
            className="flex-none h-3 w-3"
            style={{ color: STATE.working }}
          />
        ) : isWorking || isRetrying ? (
          <svg
            aria-hidden="true"
            className="flex-none h-3 w-3"
            viewBox="0 0 14 14"
          >
            <circle
              cx="7" cy="7" r="5.5"
              fill="none"
              stroke={markerColor}
              strokeWidth="1.5"
              strokeDasharray="10 28"
              strokeLinecap="round"
              style={{ animation: "tool-spinner 1.1s linear infinite" }}
            />
          </svg>
        ) : (
          <span
            aria-hidden="true"
            className="relative flex-none w-2 h-2 rounded-full"
            style={{
              background: markerColor,
              opacity: isStarting ? 0.5 : 1,
            }}
          />
        )}

        {/* Slugs */}
        <span className="flex-1 min-w-0 text-[13px] font-medium tracking-[-0.015em] truncate">
          {agent.slugs.map((slug, i) => (
            <span key={slug}>
              <span style={{ color: existingSlugs.has(slug) ? C.existing : C.fgStrong }}>
                {slug}
              </span>
              {i < agent.slugs.length - 1 && <span style={{ color: C.fgMuted }}>, </span>}
            </span>
          ))}
        </span>

        {/* Retry badge */}
        {isRetrying && (
          <span
            className="text-[10.5px] tabular-nums flex-none px-1.5 py-0.5 rounded"
            style={{
              color: STATE.retry,
              background: `${STATE.retry}14`,
              fontFamily: MONO,
            }}
          >
            retry {agent.retryAttempt}
          </span>
        )}

        {/* Chevron toggle */}
        <button
          type="button"
          onClick={() => setUserToggled(!expanded)}
          aria-expanded={expanded}
          aria-controls={detailId}
          aria-label={expanded ? "Collapse details" : "Expand details"}
          className="flex-none w-5 h-5 flex items-center justify-center rounded hover:bg-white/5 transition-colors"
        >
          <ChevronRight
            className="h-3 w-3 transition-transform duration-200"
            style={{
              color: C.fgDim,
              transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            }}
          />
        </button>
      </div>

      {/* Row 2: latest activity (or error/retry message) */}
      {!isStarting && (
        <LatestActivityRow
          agent={agent}
          latestActivity={latestActivity}
          isStopped={isStopped}
        />
      )}

      {/* Expanded detail */}
      <div
        id={detailId}
        role="region"
        aria-label="Agent details"
        className="overflow-hidden transition-all ease-out"
        style={{
          maxHeight: expanded ? "1200px" : "0",
          opacity: expanded ? 1 : 0,
          transitionDuration: "220ms",
        }}
      >
        <div
          className="mx-3 mb-3 mt-1 p-3 rounded-lg flex flex-col gap-3"
          style={{ background: C.detailZone }}
        >
          {agent.instruction && (
            <Section label="Instruction">
              <div
                className="text-[12px] leading-relaxed whitespace-pre-wrap break-words"
                style={{ color: C.fgLabel }}
              >
                {agent.instruction}
              </div>
            </Section>
          )}

          {agent.activity.length > 0 && (
            <Section
              label={`Activity · ${agent.activity.length} step${agent.activity.length === 1 ? "" : "s"}`}
            >
              <ActivityTimeline
                activity={agent.activity}
                showThinking={
                  !isStopped &&
                  (isWorking || isRetrying) &&
                  agent.activity[agent.activity.length - 1]?.status !== "active"
                }
              />
            </Section>
          )}

          {isError && agent.errorMsg && (
            <div
              className="text-[11.5px] p-2.5 rounded-md leading-relaxed"
              style={{ background: `${STATE.error}14`, color: STATE.error }}
            >
              {agent.errorMsg}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// --- Row 2: Latest activity / state message --------------------------------

function LatestActivityRow({
  agent,
  latestActivity,
  isStopped,
}: {
  agent: AgentState
  latestActivity: AgentState["activity"][number] | null
  isStopped: boolean
}) {
  // Stopped by user: show static "Stopped" label, no spinner
  if (isStopped) {
    return (
      <div className="pl-[38px] pr-3 pb-2 flex items-center gap-1.5">
        <span className="flex-none w-2 h-2 rounded-full" style={{ background: C.fgMuted }} />
        <span className="text-[11.5px] truncate tracking-[-0.005em]" style={{ color: C.fgMuted }}>
          Stopped
        </span>
      </div>
    )
  }

  // Error: show error message truncated, red
  if (agent.status === "error") {
    return (
      <div className="pl-[38px] pr-3 pb-2 flex items-center gap-1.5">
        <AlertCircle className="flex-none h-3 w-3" style={{ color: STATE.error }} />
        <span
          className="text-[11.5px] truncate tracking-[-0.005em]"
          style={{ color: STATE.error }}
        >
          {agent.errorMsg || "Failed"}
        </span>
      </div>
    )
  }

  // Retrying: show retry reason, amber
  if (agent.status === "retrying") {
    return (
      <div className="pl-[38px] pr-3 pb-2 flex items-center gap-1.5">
        <RefreshCw
          className="flex-none h-3 w-3"
          style={{ color: STATE.retry, animation: "tool-spinner 1.2s linear infinite" }}
        />
        <span
          className="text-[11.5px] truncate tracking-[-0.005em]"
          style={{ color: STATE.retry }}
        >
          {agent.errorMsg || `Retrying (${agent.retryAttempt})`}
        </span>
      </div>
    )
  }

  // Done: show the last activity (no Thinking, no dots)
  if (agent.status === "done") {
    if (!latestActivity) return null
    const catColor = CAT[latestActivity.category].accent
    const meta = getToolMeta(latestActivity.tool)
    const labelColor = `color-mix(in oklch, ${catColor} 55%, ${C.fgDim})`
    return (
      <div className="pl-[38px] pr-3 pb-2 flex items-center gap-1.5">
        <meta.Icon className="flex-none h-3 w-3" style={{ color: catColor }} />
        <span
          className="text-[11.5px] truncate tracking-[-0.005em]"
          style={{ color: labelColor }}
        >
          {latestActivity.label}
        </span>
      </div>
    )
  }

  // No activity yet, or last activity already finished → Thinking
  const isThinking = !latestActivity || latestActivity.status !== "active"
  if (isThinking) {
    return (
      <div className="pl-[38px] pr-3 pb-2 flex items-center gap-1.5">
        <Sparkles className="flex-none h-3 w-3" style={{ color: C.fgDim }} />
        <span className="text-[11.5px] truncate tracking-[-0.005em]" style={{ color: C.fgDim }}>
          Thinking<span className="thinking-dots" aria-hidden="true" />
        </span>
      </div>
    )
  }

  const isErrStep = latestActivity.status === "error"
  const catColor = CAT[latestActivity.category].accent
  const meta = getToolMeta(latestActivity.tool)

  const iconColor = isErrStep ? STATE.error : catColor
  const labelColor = isErrStep
    ? STATE.error
    : `color-mix(in oklch, ${catColor} 85%, white 15%)`

  return (
    <div className="pl-[38px] pr-3 pb-2 flex items-center gap-1.5">
      <meta.Icon
        className="flex-none h-3 w-3"
        style={{ color: iconColor }}
      />
      <span
        className="text-[11.5px] truncate tracking-[-0.005em]"
        style={{ color: labelColor }}
      >
        {latestActivity.label}
        <span className="thinking-dots" aria-hidden="true" />
        {isErrStep ? "  ✗" : ""}
      </span>
    </div>
  )
}

// --- Section (uppercase label + children) ----------------------------------

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        className="text-[9.5px] font-medium uppercase mb-1.5"
        style={{ color: C.smallLabel, letterSpacing: "0.14em" }}
      >
        {label}
      </div>
      {children}
    </div>
  )
}

// --- ActivityTimeline ------------------------------------------------------

function ActivityTimeline({ activity, showThinking }: { activity: AgentState["activity"]; showThinking: boolean }) {
  return (
    <ol className="flex flex-col gap-1">
      {activity.map((a) => {
        const catColor = CAT[a.category].accent
        const meta = getToolMeta(a.tool)
        const isActive = a.status === "active"
        const isErr = a.status === "error"

        const iconColor = isErr ? STATE.error : catColor
        const labelColor = isErr
          ? STATE.error
          : `color-mix(in oklch, ${catColor} 75%, white 25%)`

        return (
          <li key={a.toolUseId} className="flex items-center gap-2">
            <meta.Icon
              className="flex-none h-3 w-3"
              style={{ color: iconColor }}
            />
            <span
              className="text-[11.5px] truncate tracking-[-0.005em]"
              style={{ color: labelColor }}
            >
              {a.label}
              {isActive && <span className="thinking-dots" aria-hidden="true" />}
              {isErr ? "  ✗" : ""}
            </span>
          </li>
        )
      })}
      {showThinking && (
        <li className="flex items-center gap-2">
          <Sparkles className="flex-none h-3 w-3" style={{ color: C.fgDim }} />
          <span className="text-[11.5px] truncate tracking-[-0.005em]" style={{ color: C.fgDim }}>
            Thinking<span className="thinking-dots" aria-hidden="true" />
          </span>
        </li>
      )}
    </ol>
  )
}
