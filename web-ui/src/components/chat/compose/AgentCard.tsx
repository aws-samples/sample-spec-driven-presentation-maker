// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentCard v2 — One composer agent inside ComposeCard.
 *
 * Uses work-ledger grammar:
 * - Collapsed: dot/cursor marker + agent name + slugs + latest activity + chevron
 * - Expanded: job-note instruction (agent-color left rule) + nested activity
 *   timeline rail (same visual language as ToolCard group feeds)
 *
 * Preserves: error auto-expand, retry/rushed badges, aria-expanded, status.
 */

"use client"

import { useState } from "react"
import { useTranslations } from "next-intl"
import { ChevronRight, AlertCircle, RefreshCw, Sparkles } from "lucide-react"
import type { AgentState } from "./parseComposeState"
import { STATE, C, MONO, getToolMeta, getAgentIdentity, agentColor } from "./composeTokens"
import { CAT } from "../toolPalette"

interface AgentCardProps {
  agent: AgentState
  existingSlugs: Set<string>
  indexDelay: number
  parentActive: boolean
  parentStopped: boolean
  parentStopping: boolean
}

export function AgentCard({ agent, existingSlugs, indexDelay, parentActive, parentStopped, parentStopping }: AgentCardProps) {
  const t = useTranslations("compose")
  const [userToggled, setUserToggled] = useState<boolean | null>(null)
  // Default expansion: expand only when the parent compose is finished AND this
  // agent ended in error. Mid-run transient errors should not auto-open.
  const expanded = userToggled ?? (!parentActive && agent.status === "error")

  // Agent identity — cyclic assignment
  const identity = getAgentIdentity(agent.groupIndex)
  const myColor = agentColor(identity)

  // Stopped: parent card determined this compose was stopped and this agent
  // never reached a terminal state.
  const isStopped = parentStopped && agent.status !== "done" && agent.status !== "error"
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

  return (
    <div
      className="ledger-row relative flex items-start gap-2.5 py-1.5"
      style={{
        animation: `compose-card-enter 500ms cubic-bezier(0.22, 1, 0.36, 1) ${indexDelay * 80}ms both`,
      }}
    >
      {/* Left rail marker — agent-color dot/cursor */}
      <div className="ledger-marker flex-none flex flex-col items-center pt-1">
        {(isWorking || isRetrying || isStoppingInFlight) && !isDone ? (
          /* Cursor arrow + agent name tag = active */
          <div className="flex items-center gap-1">
            <svg
              className="w-2.5 h-2.5 ledger-cursor"
              viewBox="0 0 10 10"
              fill="none"
              aria-hidden="true"
            >
              <path d="M1 1 L9 5 L5 5.8 L3.5 9.5 Z" fill={isError ? STATE.error : isStoppingInFlight ? STATE.retry : myColor} />
            </svg>
            <span
              className="text-[11px] font-medium leading-none px-1 py-0.5 rounded-sm"
              style={{
                color: isStoppingInFlight ? STATE.retry : myColor,
                background: `color-mix(in oklch, ${isStoppingInFlight ? STATE.retry : myColor} 10%, transparent)`,
              }}
            >
              {identity.name}
            </span>
          </div>
        ) : isError ? (
          /* Red dot = error */
          <div
            className="w-2 h-2 rounded-full tool-check-enter"
            style={{ background: STATE.error }}
            aria-hidden="true"
          />
        ) : isDone ? (
          /* Agent-color dot = done */
          <div
            className="w-2 h-2 rounded-full tool-check-enter"
            style={{ background: myColor }}
            aria-hidden="true"
          />
        ) : (
          /* Muted dot = starting/idle */
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: myColor, opacity: 0.4 }}
            aria-hidden="true"
          />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Row 1: slugs + latest activity inline + badges */}
        <div className="flex items-center gap-1.5 min-h-[20px]">
          {/* Slugs */}
          <span className="flex-none text-xs font-medium tracking-[-0.015em] truncate max-w-[40%]">
            {agent.slugs.map((slug, i) => (
              <span key={slug}>
                <span style={{ color: existingSlugs.has(slug) ? C.existing : C.fgStrong }}>
                  {slug}
                </span>
                {i < agent.slugs.length - 1 && <span style={{ color: C.fgMuted }}>, </span>}
              </span>
            ))}
          </span>

          {/* Latest activity / state (inline) */}
          <span className="flex-1 min-w-0 truncate">
            <LatestActivityInline
              agent={agent}
              latestActivity={latestActivity}
              isStopped={isStopped}
              isStoppingInFlight={isStoppingInFlight}
            />
          </span>

          {/* Retry badge */}
          {isRetrying && (
            <span
              className="flex-none text-[11px] tabular-nums px-1.5 py-0.5 rounded"
              style={{
                color: STATE.retry,
                background: `color-mix(in oklch, ${STATE.retry} 10%, transparent)`,
                fontFamily: MONO,
              }}
            >
              {t("retryBadge", { count: agent.retryAttempt })}
            </span>
          )}

          {/* Budget nudge badge */}
          {agent.budgetReached && (
            <span
              role="status"
              aria-live="polite"
              className="flex-none text-[11px] px-1.5 py-0.5 rounded animate-in fade-in slide-in-from-right-1 duration-300"
              style={{
                color: STATE.retry,
                background: `color-mix(in oklch, ${STATE.retry} 10%, transparent)`,
                fontFamily: MONO,
              }}
              title={t("rushedAgentTitle")}
            >
              {t("rushedAgent")}
            </span>
          )}

          {/* Chevron toggle */}
          <button
            type="button"
            onClick={() => setUserToggled(!expanded)}
            aria-expanded={expanded}
            aria-controls={detailId}
            aria-label={expanded ? t("collapseDetails") : t("expandDetails")}
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

        {/* Expanded detail panel */}
        <div
          id={detailId}
          role="region"
          aria-label={t("agentDetails")}
          className="overflow-hidden transition-all ease-out"
          style={{
            maxHeight: expanded ? "1200px" : "0",
            opacity: expanded ? 1 : 0,
            transitionDuration: "220ms",
          }}
        >
          <div className="mt-2 mb-1 flex flex-col gap-3">
            {/* Job-note: instruction with agent-color left rule */}
            {agent.instruction && (
              <div
                className="pl-3 py-2 rounded-r-md"
                style={{
                  borderLeft: `2px solid ${myColor}`,
                  background: `color-mix(in oklch, ${myColor} 4%, transparent)`,
                }}
              >
                <div className="text-[9.5px] font-medium uppercase mb-1" style={{ color: C.smallLabel, letterSpacing: "0.14em" }}>
                  {t("instruction")}
                </div>
                <div
                  className="text-xs leading-relaxed whitespace-pre-wrap break-words"
                  style={{ color: C.fgLabel }}
                >
                  {agent.instruction}
                </div>
              </div>
            )}

            {/* Activity timeline (nested rail) */}
            {agent.activity.length > 0 && (
              <div>
                <div className="text-[9.5px] font-medium uppercase mb-1.5" style={{ color: C.smallLabel, letterSpacing: "0.14em" }}>
                  {t("activitySteps", { count: agent.activity.length })}
                </div>
                <ActivityTimeline
                  activity={agent.activity}
                  agentColor={myColor}
                  showThinking={
                    !isStopped &&
                    (isWorking || isRetrying) &&
                    agent.activity[agent.activity.length - 1]?.status !== "active"
                  }
                />
              </div>
            )}

            {/* Error message */}
            {isError && agent.errorMsg && (
              <div
                className="text-[11px] p-2.5 rounded-md leading-relaxed"
                style={{ background: `color-mix(in oklch, ${STATE.error} 8%, transparent)`, color: STATE.error }}
              >
                {agent.errorMsg}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// --- Latest Activity Inline (collapsed row) --------------------------------

function LatestActivityInline({
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
  const t = useTranslations("compose")

  if (isStopped) {
    return (
      <span className="text-[11px] truncate" style={{ color: C.fgMuted }}>
        {t("stopped")}
      </span>
    )
  }

  if (isStoppingInFlight) {
    return (
      <span className="text-[11px] truncate" style={{ color: STATE.retry }}>
        {t("stoppingBare")}<span className="thinking-dots" aria-hidden="true" />
      </span>
    )
  }

  if (agent.status === "error") {
    return (
      <span className="text-[11px] truncate" style={{ color: STATE.error }}>
        {agent.errorMsg || t("agentFailed")}
      </span>
    )
  }

  if (agent.status === "retrying") {
    return (
      <span className="text-[11px] truncate" style={{ color: STATE.retry }}>
        {agent.errorMsg || t("retrying", { count: agent.retryAttempt })}
      </span>
    )
  }

  if (agent.status === "done" && latestActivity) {
    const catColor = CAT[latestActivity.category].accent
    return (
      <span className="text-[11px] truncate" style={{ color: `color-mix(in oklch, ${catColor} 55%, var(--muted-foreground))` }}>
        {latestActivity.label}
      </span>
    )
  }

  // Active — show latest tool or "Thinking"
  if (latestActivity && latestActivity.status === "active") {
    const catColor = CAT[latestActivity.category].accent
    return (
      <span className="text-[11px] truncate" style={{ color: `color-mix(in oklch, ${catColor} 75%, var(--foreground))` }}>
        {latestActivity.label}<span className="thinking-dots" aria-hidden="true" />
      </span>
    )
  }

  // No activity or between steps → Thinking
  if (agent.status === "starting") return null
  return (
    <span className="text-[11px] truncate" style={{ color: C.fgDim }}>
      {t("thinking")}<span className="thinking-dots" aria-hidden="true" />
    </span>
  )
}

// --- Activity Timeline (nested rail, expanded view) ------------------------

function ActivityTimeline({ activity, agentColor: myColor, showThinking }: { activity: AgentState["activity"]; agentColor: string; showThinking: boolean }) {
  const t = useTranslations("compose")
  return (
    <ol
      className="flex flex-col gap-0.5 pl-3 border-l"
      style={{ borderColor: `color-mix(in oklch, ${myColor} 20%, transparent)` }}
    >
      {activity.map((a) => {
        const catColor = CAT[a.category].accent
        const meta = getToolMeta(a.tool)
        const isActive = a.status === "active"
        const isErr = a.status === "error"

        const iconColor = isErr ? STATE.error : catColor
        const labelColor = isErr
          ? STATE.error
          : isActive
          ? `color-mix(in oklch, ${catColor} 85%, var(--foreground))`
          : C.fgMuted

        return (
          <li key={a.toolUseId} className="relative flex items-center gap-2 py-0.5">
            {/* Sub-marker on the rail */}
            <div className="absolute left-0 -translate-x-1/2 -ml-3 flex-none">
              {isErr ? (
                <div className="w-1.5 h-1.5 rounded-full" style={{ background: STATE.error }} />
              ) : isActive ? (
                <div className="w-1.5 h-1.5 rounded-full" style={{ background: catColor, animation: "tool-pulse 1.5s ease-in-out infinite" }} />
              ) : (
                <div className="w-1 h-1 rounded-full" style={{ background: catColor, opacity: 0.5 }} />
              )}
            </div>
            <meta.Icon
              className="flex-none h-3 w-3"
              style={{ color: iconColor }}
            />
            <span
              className="text-[11px] truncate tracking-[-0.005em]"
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
        <li className="relative flex items-center gap-2 py-0.5">
          <div className="absolute left-0 -translate-x-1/2 -ml-3 flex-none">
            <div className="w-1 h-1 rounded-full" style={{ background: myColor, opacity: 0.3, animation: "tool-pulse 1.5s ease-in-out infinite" }} />
          </div>
          <Sparkles className="flex-none h-3 w-3" style={{ color: C.fgDim }} />
          <span className="text-[11px] truncate tracking-[-0.005em]" style={{ color: C.fgDim }}>
            {t("thinking")}<span className="thinking-dots" aria-hidden="true" />
          </span>
        </li>
      )}
    </ol>
  )
}
