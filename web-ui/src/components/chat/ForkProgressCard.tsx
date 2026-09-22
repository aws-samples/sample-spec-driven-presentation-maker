// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

"use client"

import { useEffect, useState } from "react"
import { Check, GitBranch, Loader2 } from "lucide-react"
import { useTranslations } from "next-intl"

import type { ForkSessionPhase, KiroSessionSummary } from "@/lib/local/kiro-sessions.types"

interface ForkProgressCardProps {
  session: KiroSessionSummary
  phase: ForkSessionPhase
  replayed: number
  onCancel: () => void
}

const PHASES: ForkSessionPhase[] = ["copying", "starting", "loading", "switching"]

export function ForkProgressCard({ session, phase, replayed, onCancel }: ForkProgressCardProps) {
  const t = useTranslations("forkProgress")
  const [showHint, setShowHint] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => setShowHint(true), 8000)
    return () => window.clearTimeout(timer)
  }, [])

  const activeIndex = PHASES.indexOf(phase)
  const phaseLabels: Record<ForkSessionPhase, string> = {
    copying: t("copying"),
    starting: t("starting"),
    loading: t("loading"),
    switching: t("switching"),
  }

  return (
    <div className="flex h-full items-center justify-center px-4 py-6">
      <section className="w-full max-w-sm rounded-2xl border border-border bg-background px-5 py-5 shadow-sm" aria-labelledby="fork-progress-title">
        <header className="flex min-w-0 items-start gap-3 border-b border-border pb-4">
          <span className="flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-brand-teal-soft text-brand-teal">
            <GitBranch className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <h2 id="fork-progress-title" className="truncate text-sm font-semibold text-foreground" title={session.title}>
              {session.title}
            </h2>
            <span className="mt-1 block truncate text-xs text-foreground-muted">
              {t("sessionMeta", { project: session.project, count: session.messageCount })}
            </span>
          </span>
        </header>

        <ol className="mt-4 space-y-3" aria-label={t("stepsLabel")}>
          {PHASES.map((step, index) => {
            const state = index < activeIndex ? "completed" : index === activeIndex ? "active" : "pending"
            const label = step === "loading" && state === "active"
              ? t("loadingWithCount", { count: replayed })
              : phaseLabels[step]
            return (
              <li key={step} data-state={state} className="flex min-h-6 items-center gap-3">
                {state === "completed" ? (
                  <span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-brand-teal text-white">
                    <Check className="h-3 w-3" aria-hidden="true" />
                  </span>
                ) : state === "active" ? (
                  <Loader2 className="h-5 w-5 flex-none text-brand-teal motion-safe:animate-spin" aria-hidden="true" />
                ) : (
                  <span className="h-5 w-5 flex-none rounded-full border-2 border-foreground/10" aria-hidden="true" />
                )}
                <span className={`text-sm ${state === "pending" ? "text-foreground-muted" : "font-medium text-foreground"} ${step === "loading" && state === "active" ? "tabular-nums" : ""}`}>
                  {label}
                </span>
              </li>
            )
          })}
        </ol>

        <p role="status" aria-live="polite" className="sr-only">{phaseLabels[phase]}</p>

        <footer className="mt-4 border-t border-border pt-3">
          <div className="flex min-h-10 items-center justify-center">
            {showHint && (
              <p className="text-center text-xs leading-relaxed text-foreground-muted motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-300">
                {t("slowHint")}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="mt-2 min-h-11 w-full rounded-xl border border-border px-4 text-sm font-medium text-foreground-secondary motion-safe:transition-colors hover:border-border-hover hover:bg-background-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
          >
            {t("cancel")}
          </button>
        </footer>
      </section>
    </div>
  )
}
