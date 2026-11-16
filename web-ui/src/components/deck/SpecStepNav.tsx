// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SpecStepNav — Kiro-inspired step navigation for spec files.
 *
 * Displays a horizontal step bar: 1 Brief → 2 Outline → 3 Art Direction → ◆ Slides.
 * Spec tabs are grayed out when content is null, and auto-focus when content appears.
 * When a spec tab is active, renders markdown content with prose styling.
 *
 * @param props.specs - Spec file contents (null = not yet created)
 * @param props.activeTab - Currently active tab key
 * @param props.onTabChange - Callback when user clicks a tab
 * @param props.slideCount - Number of slides (shown as badge on Slides tab)
 */

"use client"

import { Layers } from "lucide-react"
import type { SpecFiles } from "@/services/deckService"
import { useTranslations } from "next-intl"
import { deckDisplay } from "@/lib/deckTitle"

// Re-exported for existing consumers (SlideCarousel imports from here).
export { SpecMarkdownPreview } from "./SpecMarkdownPreview"
export { renderColorSwatches } from "./colorSwatches"

/** Tab key union type for spec viewer navigation. */
export type SpecTab = "brief" | "outline" | "artDirection" | "slides"

/** Step definition for the navigation bar. */
interface StepDef {
  key: SpecTab
  label: string
  step?: number
}

// label is the en fallback; display text resolves via specNav.<key>
const STEPS: StepDef[] = [
  // Order follows the orchestrator workflow: the style (art direction) is chosen
  // before the outline because its Message & Outline part fixes deck length,
  // density, title grammar and chapter shape.
  { key: "brief", label: "Brief", step: 1 },
  { key: "artDirection", label: "Art Direction", step: 2 },
  { key: "outline", label: "Outline", step: 3 },
  { key: "slides", label: "Slides" },
]

interface SpecStepNavProps {
  specs: SpecFiles | null | undefined
  activeTab: SpecTab
  onTabChange: (tab: SpecTab) => void
  slideCount: number
  /** Desktop: the rail shows the deck's title above the phases. */
  deckName?: string
}

export function SpecStepNav({ specs, activeTab, onTabChange, slideCount, deckName }: SpecStepNavProps) {
  const t = useTranslations("specNav")
  /**
   * Check whether a spec tab has content.
   *
   * @param key - The spec tab key
   * @returns true if the spec file exists and has content
   */
  function hasContent(key: SpecTab): boolean {
    return true
  }

  const title = deckName ? deckDisplay(deckName).title : null

  return (
    <div className="flex-none border-b border-border/40 md:border-b-0 md:border-r md:border-border md:w-60 md:px-4 md:py-6 md:overflow-y-auto">
    {title && (
      <div className="hidden md:block px-2 mb-7">
        <h2 className="text-lg font-semibold leading-snug tracking-[-0.02em] text-foreground line-clamp-3" title={deckName}>
          {title}
        </h2>
      </div>
    )}
    {title && <p className="hidden md:block px-2 mb-2 text-xs font-medium text-foreground-muted">{t("phases")}</p>}
    <nav className="flex items-center gap-1 px-5 py-2 md:flex-col md:items-stretch md:gap-0 md:p-0" role="tablist" aria-label={t("specPhases")}>
      {STEPS.map((s, i) => {
        const isSlides = s.key === "slides"
        const active = activeTab === s.key
        const enabled = hasContent(s.key)

        return (
          <div key={s.key} className="flex items-center md:flex-col md:items-stretch">
            {/* Connector line between steps (horizontal on mobile, vertical in the rail) */}
            {i > 0 && (
              <div className={`w-4 h-px mx-1 md:w-px md:h-3 md:mx-0 md:ml-[21px] transition-colors duration-300 ${
                enabled && hasContent(STEPS[i - 1].key)
                  ? "bg-border-hover"
                  : "bg-border/30"
              }`} />
            )}

            <button
              role="tab"
              aria-selected={active}
              aria-disabled={!enabled}
              disabled={!enabled}
              onClick={() => onTabChange(s.key)}
              className={`
                relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                md:w-full md:gap-3 md:px-2.5 md:py-2 md:rounded-xl
                transition-all duration-300 select-none
                ${active
                  ? isSlides
                    ? "bg-brand-amber-soft text-brand-amber"
                    : "bg-foreground/[8%] text-foreground"
                  : enabled
                    ? "text-foreground-secondary hover:text-foreground hover:bg-background-hover"
                    : "text-foreground-muted/40 cursor-not-allowed"
                }
              `}
            >
              {/* Step number badge or Slides icon */}
              {isSlides ? (
                <span className="inline-flex items-center justify-center md:w-6 md:h-6">
                  <Layers className={`h-3.5 w-3.5 ${active ? "text-brand-amber" : ""}`} />
                </span>
              ) : (
                <span className={`
                  inline-flex items-center justify-center w-4 h-4 md:w-6 md:h-6 rounded-full text-[11px] md:text-xs font-semibold leading-none
                  transition-all duration-300
                  ${active
                    ? "bg-foreground text-background"
                    : enabled
                      ? "bg-foreground-muted/15 text-foreground-secondary"
                      : "bg-foreground-muted/8 text-foreground-muted/30"
                  }
                `}>
                  {s.step}
                </span>
              )}

              {t(s.key)}

              {/* Slide count badge */}
              {isSlides && slideCount > 0 && (
                <span className={`text-[11px] md:text-xs font-normal md:ml-auto md:tabular-nums ${active ? "text-brand-amber" : "text-foreground-muted"}`}>
                  <span className="md:hidden">· </span>{slideCount}
                </span>
              )}

              {/* Active indicator dot */}
              {active && (
                <span className={`md:hidden absolute -bottom-2.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full ${
                  isSlides ? "bg-brand-amber" : "bg-foreground"
                }`} />
              )}
            </button>
          </div>
        )
      })}
    </nav>
    </div>
  )
}
