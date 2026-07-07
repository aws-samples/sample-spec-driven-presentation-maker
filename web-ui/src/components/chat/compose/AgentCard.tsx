// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentCard — One composer agent inside ComposeCard.
 *
 * Two always-visible rows (identity / current activity) plus an inline
 * accordion with the instruction and full activity timeline.
 */

"use client"

import { useState } from "react"
import { ChevronRight, Check, AlertCircle, RefreshCw, Sparkles } from "lucide-react"
import type { AgentState } from "./parseComposeState"
import { CAT } from "../toolPalette"
import { STATE, C, MONO, getToolMeta } from "./composeTokens"

interface AgentCardProps {
  agent: AgentState
  existingSlugs: Set<string>
  indexDelay: number
  parentActive: boolean
  parentStopped: boolean
  parentStopping: boolean
}

export function AgentCard({ agent, existingSlugs, indexDelay, parentActive, parentStopped, parentStopping }: AgentCardProps) {
  const [userToggled, setUserToggled] = useState<boolean | null>(null)
  // Default expansion: expand only when the parent compose is finished AND this
  // agent ended in error. Mid-run transient errors (the agent recovers and keeps
  // working) should not auto-open the detail panel.
  const expanded = userToggled ?? (!parentActive && agent.status === "error")

  // Stopped: parent card determined this compose was stopped and this agent
  // never reached a terminal state. Treat as done-but-incomplete; suppress spinners.
  const isStopped = parentStopped && agent.status !== "done" && agent.status !== "error"
  // Stopping-in-flight: parent asked us to stop but this agent is still working.
  // Indicates "cancellation in progress" — amber accent instead of violet.
  const isStoppingInFlight = parentStopping && agent.status !== "done" && agent.status !== "error"
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
  const markerColor = isError
    ? STATE.error
    : isStoppingInFlight
    ? STATE.retry
    : isRetrying
    ? STATE.retry
    : STATE.working

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
        <span className="flex-1 min-w-0 text-sm font-medium tracking-[-0.015em] truncate">
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

        {/* Budget nudge badge — this composer hit the time budget and was asked to wrap up */}
        {agent.budgetReached && (
          <span
            role="status"
            aria-live="polite"
            className="text-[10.5px] flex-none px-1.5 py-0.5 rounded animate-in fade-in slide-in-from-right-1 duration-300"
            style={{
              color: STATE.retry,
              background: `${STATE.retry}14`,
              fontFamily: MONO,
            }}
            title="Time budget reached — this composer wrote a rough draft to finish on time. Consider re-running for these slides."
          >
            rushed
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
          isStoppingInFlight={isStoppingInFlight}
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
                className="text-xs leading-relaxed whitespace-pre-wrap break-words"
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
  isStoppingInFlight,
}: {
  agent: AgentState
  latestActivity: AgentState["activity"][number] | null
  isStopped: boolean
  isStoppingInFlight: boolean
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

  // Stopping-in-flight: parent requested cancel but this agent hasn't wrapped
  // up yet. Show amber "Stopping…" so the user sees cancellation is propagating.
  if (isStoppingInFlight) {
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
          Stopping<span className="thinking-dots" aria-hidden="true" />
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
