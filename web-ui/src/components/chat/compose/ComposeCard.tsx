// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Compose production board.
 *
 * Progress is driven by composer-agent completion (per-group `status: "done"`
 * stream events), not by slide file existence — after a layout pass every
 * slides/<slug>.json already exists, so file presence says nothing about the
 * current pass. Tool completion remains the source of truth for overall
 * completion. Lanes keep stable order, expose the latest tool action while
 * collapsed, and allow one manually selected history.
 */

"use client"

import { useMemo, useState } from "react"
import { AlertCircle, Check } from "lucide-react"
import { useTranslations } from "next-intl"
import { parseComposeState, type ComposeState } from "./parseComposeState"
import { STATE, C, MONO } from "./composeTokens"
import { AgentCard } from "./AgentCard"

interface ComposeCardProps {
  input?: Record<string, unknown>
  status?: "success" | "error"
  isActive: boolean
  streamMessages?: Record<string, unknown>[]
}

export function ComposeCard({
  input,
  status,
  isActive,
  streamMessages = [],
}: ComposeCardProps) {
  const t = useTranslations("compose")
  const [expandedGroup, setExpandedGroup] = useState<number | null>(null)
  const state: ComposeState = useMemo(
    () => parseComposeState(streamMessages, input, t),
    [streamMessages, input, t],
  )

  const hasError = status === "error" || state.agents.some((agent) => agent.status === "error")
  // The turn was stopped (main stop button) while this tool was running.
  const isStopped = !isActive && !hasError && !status && state.agents.length > 0
  const isDone = !isActive && !isStopped && !hasError && (status === "success" || state.phase === "done")
  // Tool completion is the source of truth: a lane with no terminal stream state is done.
  const agents = isDone
    ? state.agents.map((a) => a.status === "starting" || a.status === "working" ? { ...a, status: "done" as const } : a)
    : state.agents

  // A slug counts as created once the composer agent owning it has finished
  // (or the whole tool has completed successfully).
  const expectedSlugs = [...new Set(state.agents.flatMap((agent) => agent.slugs))]
  const createdSlugs = new Set<string>()
  for (const agent of agents) {
    if (agent.status === "done" || isDone) agent.slugs.forEach((slug) => createdSlugs.add(slug))
  }
  const totalSlides = expectedSlugs.length
  const createdSlides = expectedSlugs.filter((slug) => createdSlugs.has(slug)).length
  const creationPercent = totalSlides > 0 ? Math.min(100, Math.round((createdSlides / totalSlides) * 100)) : 0
  const doneSlides = new Set(
    agents.filter((agent) => agent.status === "done").flatMap((agent) => agent.slugs),
  ).size

  return (
    <section
      aria-label={t("composingAria")}
      className="compose-card tool-card-enter relative overflow-hidden rounded-xl"
      style={{
        background: hasError
          ? "color-mix(in oklch, var(--state-error) 4%, var(--surface-subtle))"
          : "var(--surface-subtle)",
        boxShadow: hasError
          ? "inset 0 0 0 1px color-mix(in oklch, var(--state-error) 15%, transparent)"
          : "inset 0 0 0 1px var(--border)",
      }}
    >
      <div className="compose-curtain absolute inset-x-0 top-0 h-0.5" style={{ background: "var(--team-gradient)" }} aria-hidden="true" />

      <Header
        state={state}
        isDone={isDone}
        isStopped={isStopped}
        hasError={hasError}
        totalSlides={totalSlides}
        doneSlides={doneSlides}
        isActive={isActive}
      />

      {totalSlides > 0 && (
        <div className="px-4 pb-3">
          <div className="mb-1.5 flex items-center justify-between gap-3 text-[11px]">
            <span className="text-foreground-muted">{t("slideCreation")}</span>
            <span className="tabular-nums text-foreground-secondary" style={{ fontFamily: MONO }}>
              {t("createdProgress", { created: createdSlides, total: totalSlides })}
            </span>
          </div>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-foreground/[10%]"
            role="progressbar"
            aria-label={t("slideCreation")}
            aria-valuemin={0}
            aria-valuemax={totalSlides}
            aria-valuenow={createdSlides}
          >
            <div
              className="h-full rounded-full transition-[width] duration-300"
              style={{ width: `${creationPercent}%`, background: "var(--team-gradient)" }}
            />
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-foreground-secondary">
            {isActive && <span className="h-2.5 w-2.5 rounded-full border border-border-hover border-t-foreground-secondary" style={{ animation: "tool-spinner 1.2s linear infinite" }} aria-hidden="true" />}
            {!isActive && isDone && <Check className="h-3 w-3" aria-hidden="true" />}
            <span>{creationStatus(state, isActive, isDone, totalSlides, createdSlides, t)}</span>
          </div>
        </div>
      )}

      <div className="flex flex-col px-2 pb-2">
        {agents.map((agent, index) => (
          <AgentCard
            key={agent.groupIndex}
            agent={agent}
            existingSlugs={createdSlugs}
            indexDelay={index}
            parentStopped={isStopped}
            expanded={expandedGroup === agent.groupIndex}
            onToggle={() => setExpandedGroup((current) => current === agent.groupIndex ? null : agent.groupIndex)}
          />
        ))}
      </div>

      <span className="sr-only" aria-live="polite">
        {t("srCreationProgress", { created: createdSlides, total: totalSlides })}
      </span>
    </section>
  )
}

function creationStatus(
  state: ComposeState,
  isActive: boolean,
  isDone: boolean,
  totalSlides: number,
  createdSlides: number,
  t: ReturnType<typeof useTranslations<"compose">>,
): string {
  if (isDone) return t("readyForReview")
  if (state.statusMessage) return state.statusMessage
  if (isActive && totalSlides > 0 && createdSlides >= totalSlides) return t("finishingPresentation")
  return t("composingSlides")
}

function Header({
  state,
  isDone,
  isStopped,
  hasError,
  totalSlides,
  doneSlides,
  isActive,
}: {
  state: ComposeState
  isDone: boolean
  isStopped: boolean
  hasError: boolean
  totalSlides: number
  doneSlides: number
  isActive: boolean
}) {
  const t = useTranslations("compose")
  const hasAgents = state.totalGroups > 0
  const isFinished = isDone || (hasError && !isActive) || isStopped
  const label = isStopped
    ? doneSlides > 0 ? t("stoppedPartial", { done: doneSlides, total: totalSlides }) : t("stopped")
    : hasError && !isActive
      ? doneSlides > 0 ? t("composedPartialFailed", { done: doneSlides, total: totalSlides }) : t("failed")
      : isDone
        ? t("composed", { count: totalSlides || state.totalGroups })
        : hasAgents
          ? t("inProduction", { count: totalSlides })
          : state.statusMessage || t("preparing")

  const accent = hasError ? STATE.error : isStopped ? C.fgMuted : C.fgLabel

  return (
    <header className="flex items-start gap-3 px-4 pb-2 pt-4">
      <div className="min-w-0 flex-1">
        <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-foreground-muted">{t("liveProduction")}</div>
        <div className="truncate text-sm font-semibold tracking-[-0.015em]" style={{ color: accent }} aria-live="polite">{label}</div>
        {hasAgents && !isFinished && (
          <div className="mt-1 text-[11px] text-foreground-muted">{t("parallelLanes", { count: state.totalGroups })}</div>
        )}
      </div>

      {hasError && !isActive && (
        <AlertCircle className="mt-1 h-4 w-4 flex-none text-state-error" aria-hidden="true" />
      )}
    </header>
  )
}
