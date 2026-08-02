// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * One observable composer lane inside ComposeCard.
 *
 * Lane numbers are neutral. Tool icon/color communicates the latest action;
 * status is communicated by shape and copy. Expanded history contains only
 * events received from the stream, plus one compact previous-attempt error.
 */

"use client"

import { AlertCircle, Check, ChevronRight, RefreshCw, Sparkles } from "lucide-react"
import { useTranslations } from "next-intl"
import type { AgentState } from "./parseComposeState"
import { STATE, C, MONO, getToolMeta } from "./composeTokens"
import { CAT } from "../toolPalette"

interface AgentCardProps {
  agent: AgentState
  existingSlugs: Set<string>
  indexDelay: number
  parentStopped: boolean
  parentStopping: boolean
  expanded: boolean
  onToggle: () => void
}

export function AgentCard({
  agent,
  existingSlugs,
  indexDelay,
  parentStopped,
  parentStopping,
  expanded,
  onToggle,
}: AgentCardProps) {
  const t = useTranslations("compose")
  const isStopped = parentStopped && agent.status !== "done" && agent.status !== "error"
  const isStoppingInFlight = parentStopping && agent.status !== "done" && agent.status !== "error"
  const isWorking = agent.status === "working" && !isStopped
  const isRetrying = agent.status === "retrying" && !isStopped
  const isError = agent.status === "error"
  const latestActivity = agent.activity.at(-1) ?? null
  const latestColor = isError
    ? STATE.error
    : isRetrying || isStoppingInFlight
      ? STATE.retry
      : latestActivity
        ? CAT[latestActivity.category].accent
        : C.fgDim
  const detailId = `compose-agent-${agent.groupIndex}-detail`
  const createdCount = agent.slugs.filter((slug) => existingSlugs.has(slug)).length

  return (
    <div
      className="compose-agent-enter rounded-lg transition-colors duration-200"
      style={{
        "--compose-delay": `${indexDelay * 55}ms`,
        background: expanded ? `color-mix(in oklch, ${latestColor} 5%, transparent)` : "transparent",
        boxShadow: expanded ? `inset 2px 0 0 ${latestColor}` : "none",
      } as React.CSSProperties}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={detailId}
        aria-label={expanded ? t("collapseDetails") : t("expandDetails")}
        className="w-full min-h-11 grid grid-cols-[24px_minmax(0,1fr)_minmax(105px,34%)_44px] items-center gap-2 px-1 rounded-lg text-left hover:bg-foreground/[3%] transition-colors"
      >
        <span className="text-[11px] font-medium tabular-nums" style={{ color: C.fgDim, fontFamily: MONO }}>
          {String(agent.groupIndex).padStart(2, "0")}
        </span>

        <span className="min-w-0 truncate text-[11px]">
          {agent.slugs.map((slug, index) => {
            const created = existingSlugs.has(slug)
            return (
              <span key={slug} className="whitespace-nowrap">
                <span className={created ? "text-foreground font-semibold" : "text-foreground-muted"}>
                  {slug}
                  {created && (
                    <span
                      className="ml-1 inline-flex h-3 w-3 items-center justify-center rounded-full border border-border-hover align-middle text-foreground-secondary"
                      aria-label={t("slideCreated")}
                    >
                      <Check className="h-2 w-2" aria-hidden="true" />
                    </span>
                  )}
                </span>
                {index < agent.slugs.length - 1 && <span className="mx-1 text-foreground-muted">·</span>}
              </span>
            )
          })}
        </span>

        <span className="min-w-0">
          <LatestActivityInline
            agent={agent}
            latestActivity={latestActivity}
            isStopped={isStopped}
            isStoppingInFlight={isStoppingInFlight}
            createdCount={createdCount}
          />
        </span>

        <span className="touch-target flex items-center justify-center rounded-md" aria-hidden="true">
          <ChevronRight
            className="h-3 w-3 transition-transform duration-200"
            style={{ color: expanded ? latestColor : C.fgDim, transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}
          />
        </span>
      </button>

      <div
        id={detailId}
        role="region"
        aria-label={t("agentDetails")}
        className="overflow-hidden transition-all ease-out"
        style={{ maxHeight: expanded ? "1400px" : "0", opacity: expanded ? 1 : 0, transitionDuration: "220ms" }}
      >
        <div className="mx-7 mb-3 ml-9 rounded-lg border border-border bg-background/35 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-foreground">{t("activityHistory")}</span>
            <span className="text-[11px] uppercase text-foreground-muted" style={{ fontFamily: MONO }}>
              {agent.retryAttempt > 0 ? t("retryAttempt", { count: agent.retryAttempt }) : t("activitySteps", { count: agent.activity.length })}
            </span>
          </div>

          {agent.previousAttemptError && (
            <div className="mb-3 flex items-start gap-2 rounded-r-md border-l-2 border-state-error bg-state-error/[6%] px-2.5 py-2">
              <AlertCircle className="mt-0.5 h-3 w-3 flex-none text-state-error" aria-hidden="true" />
              <div className="min-w-0">
                <div className="text-[11px] font-semibold text-state-error">{t("previousAttemptFailed")}</div>
                <div className="mt-0.5 break-words text-[11px] leading-relaxed text-foreground-muted">{agent.previousAttemptError}</div>
              </div>
            </div>
          )}

          <div className="mb-2 flex items-center justify-between gap-2 text-[11px]" style={{ fontFamily: MONO }}>
            <span className="text-foreground-secondary">
              {agent.retryAttempt > 0 ? t("currentRetryAttempt", { count: agent.retryAttempt }) : t("currentAttempt")}
            </span>
            <span className="text-foreground-muted">{statusLabel(agent, isStopped, isStoppingInFlight, t)}</span>
          </div>

          {agent.instruction && (
            <div className="mb-3 border-l-2 border-foreground/25 pl-3">
              <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-foreground-muted">{t("instruction")}</div>
              <div className="whitespace-pre-wrap break-words text-xs leading-relaxed text-foreground-secondary">{agent.instruction}</div>
            </div>
          )}

          {agent.activity.length > 0 ? (
            <ActivityTimeline
              activity={agent.activity}
              showThinking={!isStopped && (isWorking || isRetrying) && agent.activity.at(-1)?.status !== "active"}
            />
          ) : (
            <div className="text-[11px] text-foreground-muted">{t("noActivity")}</div>
          )}

          {isError && agent.errorMsg && (
            <div className="mt-2 rounded-md bg-state-error/[8%] p-2.5 text-[11px] leading-relaxed text-state-error">
              {agent.errorMsg}
            </div>
          )}

          {agent.budgetReached && (
            <div className="mt-2 text-[11px] text-agent-data" title={t("rushedAgentTitle")}>{t("rushedAgent")}</div>
          )}
        </div>
      </div>
    </div>
  )
}

function statusLabel(
  agent: AgentState,
  isStopped: boolean,
  isStopping: boolean,
  t: ReturnType<typeof useTranslations<"compose">>,
): string {
  if (isStopping) return t("stoppingBare")
  if (isStopped) return t("stopped")
  if (agent.status === "error") return t("agentFailed")
  if (agent.status === "retrying") return t("retrying", { count: agent.retryAttempt })
  if (agent.status === "done") return t("completed")
  if (agent.status === "starting") return t("queued")
  return t("working")
}

function LatestActivityInline({
  agent,
  latestActivity,
  isStopped,
  isStoppingInFlight,
  createdCount,
}: {
  agent: AgentState
  latestActivity: AgentState["activity"][number] | null
  isStopped: boolean
  isStoppingInFlight: boolean
  createdCount: number
}) {
  const t = useTranslations("compose")

  if (isStopped) return <StateActivity icon={AlertCircle} label={t("stopped")} color={C.fgMuted} />
  if (isStoppingInFlight) return <StateActivity icon={RefreshCw} label={t("stoppingBare")} color={STATE.retry} spin />
  if (agent.status === "error") return <StateActivity icon={AlertCircle} label={agent.errorMsg || t("agentFailed")} color={STATE.error} />
  if (agent.status === "retrying") return <StateActivity icon={RefreshCw} label={t("retrying", { count: agent.retryAttempt })} color={STATE.retry} spin />

  if (latestActivity) {
    const meta = getToolMeta(latestActivity.tool)
    const color = CAT[latestActivity.category].accent
    const active = latestActivity.status === "active"
    return (
      <span
        className="flex min-w-0 items-center justify-end gap-1.5 truncate text-[11px]"
        style={{ color: active ? `color-mix(in oklch, ${color} 82%, var(--foreground))` : `color-mix(in oklch, ${color} 58%, var(--foreground-secondary))` }}
      >
        <meta.Icon className="h-3 w-3 flex-none" aria-hidden="true" />
        <span className="truncate">{latestActivity.label}{active && <span className="thinking-dots" aria-hidden="true" />}</span>
      </span>
    )
  }

  if (agent.status === "done") return <StateActivity icon={Check} label={t("createdCount", { created: createdCount, total: agent.slugs.length })} color={C.fgMuted} />
  if (agent.status === "starting") return <StateActivity icon={Sparkles} label={t("queued")} color={C.fgDim} />
  return <StateActivity icon={Sparkles} label={t("thinking")} color={C.fgDim} />
}

function StateActivity({ icon: Icon, label, color, spin = false }: { icon: typeof Check; label: string; color: string; spin?: boolean }) {
  return (
    <span className="flex min-w-0 items-center justify-end gap-1.5 truncate text-[11px]" style={{ color }}>
      <Icon className="h-3 w-3 flex-none" style={spin ? { animation: "tool-spinner 1.2s linear infinite" } : undefined} aria-hidden="true" />
      <span className="truncate">{label}</span>
    </span>
  )
}

function ActivityTimeline({ activity, showThinking }: { activity: AgentState["activity"]; showThinking: boolean }) {
  const t = useTranslations("compose")
  return (
    <ol className="flex flex-col gap-0.5 border-l border-border-hover pl-3">
      {activity.map((entry) => {
        const color = CAT[entry.category].accent
        const meta = getToolMeta(entry.tool)
        const active = entry.status === "active"
        const error = entry.status === "error"
        const eventColor = error ? STATE.error : color
        const labelColor = error
          ? STATE.error
          : active
            ? `color-mix(in oklch, ${color} 82%, var(--foreground))`
            : `color-mix(in oklch, ${color} 58%, var(--foreground-secondary))`

        return (
          <li key={entry.toolUseId} className="relative flex min-h-7 items-center gap-2 py-0.5">
            <span className="absolute left-0 -ml-3 flex -translate-x-1/2 items-center justify-center bg-background" aria-hidden="true">
              {error ? (
                <span className="h-1.5 w-1.5 rounded-full bg-state-error" />
              ) : active ? (
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: color, animation: "tool-pulse 1.5s ease-in-out infinite" }} />
              ) : (
                <span className="flex h-3 w-3 items-center justify-center rounded-full border border-border-hover" style={{ color }}>
                  <Check className="h-2 w-2" />
                </span>
              )}
            </span>
            <meta.Icon className="h-3 w-3 flex-none" style={{ color: eventColor }} aria-hidden="true" />
            <span className="truncate text-[11px] tracking-[-0.005em]" style={{ color: labelColor }}>
              {entry.label}{active && <span className="thinking-dots" aria-hidden="true" />}{error ? "  ✗" : ""}
            </span>
          </li>
        )
      })}
      {showThinking && (
        <li className="relative flex min-h-7 items-center gap-2 py-0.5">
          <span className="absolute left-0 -ml-3 h-1 w-1 -translate-x-1/2 rounded-full bg-foreground-muted" style={{ animation: "tool-pulse 1.5s ease-in-out infinite" }} />
          <Sparkles className="h-3 w-3 flex-none text-foreground-muted" aria-hidden="true" />
          <span className="truncate text-[11px] text-foreground-muted">{t("thinking")}<span className="thinking-dots" aria-hidden="true" /></span>
        </li>
      )}
    </ol>
  )
}
