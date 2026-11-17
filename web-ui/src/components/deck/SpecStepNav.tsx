// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SpecStepNav — Kiro-inspired step navigation for spec files.
 *
 * A connected progress track: Brief → Art Direction → Outline → Slides, one segment each.
 * A segment is filled when its step is done (the spec file exists; slides: there are some),
 * half-lit for the first step not done yet, and faint after it. Every step stays clickable.
 *
 * @param props.specs - Spec file contents (null = not yet created)
 * @param props.activeTab - Currently active tab key
 * @param props.onTabChange - Callback when user clicks a tab
 * @param props.slideCount - Number of slides (shown as badge on Slides tab)
 */

"use client"

import { Check, Layers } from "lucide-react"
import type { SpecFiles } from "@/services/deckService"
import { useTranslations } from "next-intl"

// Re-exported for existing consumers (SlideCarousel imports from here).
export { SpecMarkdownPreview } from "./SpecMarkdownPreview"
export { renderColorSwatches } from "./colorSwatches"

/** Tab key union type for spec viewer navigation. */
export type SpecTab = "brief" | "outline" | "artDirection" | "slides"

// Order follows the orchestrator workflow: the style (art direction) is chosen
// before the outline because its Message & Outline part fixes deck length,
// density, title grammar and chapter shape. Display text resolves via specNav.<key>.
const STEPS: SpecTab[] = ["brief", "artDirection", "outline", "slides"]

type StepState = "done" | "next" | "later"

interface SpecStepNavProps {
  specs: SpecFiles | null | undefined
  activeTab: SpecTab
  onTabChange: (tab: SpecTab) => void
  slideCount: number
}

export function SpecStepNav({ specs, activeTab, onTabChange, slideCount }: SpecStepNavProps) {
  const t = useTranslations("specNav")
  const done = (key: SpecTab) => (key === "slides" ? slideCount > 0 : specs?.[key] != null)
  const firstOpen = STEPS.findIndex((key) => !done(key))
  const stateOf = (i: number): StepState => (done(STEPS[i]) ? "done" : i === firstOpen ? "next" : "later")

  return (
    <nav className="flex min-w-0 items-stretch gap-1 overflow-x-auto scrollbar-hide" role="tablist" aria-label={t("specPhases")}>
      {STEPS.map((key, i) => {
        const isSlides = key === "slides"
        const active = activeTab === key
        const state = stateOf(i)
        return (
          <button
            key={key}
            role="tab"
            aria-selected={active}
            data-state={state}
            onClick={() => onTabChange(key)}
            className={`group flex min-w-0 flex-none flex-col gap-1.5 rounded-lg px-2.5 pt-1.5 pb-1 text-left select-none motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal ${
              active ? "" : "hover:bg-background-hover"
            }`}
          >
            <span className={`flex items-center gap-1.5 whitespace-nowrap text-sm ${
              active
                ? isSlides ? "font-semibold text-brand-amber" : "font-semibold text-foreground"
                : state === "later" ? "text-foreground-muted" : "text-foreground-secondary group-hover:text-foreground"
            }`}>
              {state === "done" && !isSlides && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
              {isSlides && <Layers className="h-3.5 w-3.5" aria-hidden="true" />}
              {t(key)}
              {isSlides && slideCount > 0 && (
                <span className={`text-xs font-normal tabular-nums ${active ? "text-brand-amber" : "text-foreground-muted"}`}>{slideCount}</span>
              )}
            </span>
            {/* The track: one segment per step */}
            <span aria-hidden="true" className={`block h-[3px] w-full rounded-full motion-safe:transition-colors motion-safe:duration-300 ${
              active && isSlides ? "bg-brand-amber"
                : state === "done" ? (active ? "bg-foreground" : "bg-foreground/55")
                  : state === "next" ? "step-track-next"
                    : active ? "bg-foreground/35" : "bg-foreground/10"
            }`} />
          </button>
        )
      })}
    </nav>
  )
}
