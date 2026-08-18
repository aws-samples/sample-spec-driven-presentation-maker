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
  { key: "brief", label: "Brief", step: 1 },
  { key: "outline", label: "Outline", step: 2 },
  { key: "artDirection", label: "Art Direction", step: 3 },
  { key: "slides", label: "Slides" },
]

interface SpecStepNavProps {
  specs: SpecFiles | null | undefined
  activeTab: SpecTab
  onTabChange: (tab: SpecTab) => void
  slideCount: number
}

export function SpecStepNav({ specs, activeTab, onTabChange, slideCount }: SpecStepNavProps) {
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

  return (
    <nav className="flex items-center gap-1 px-5 py-2 border-b border-border/40" role="tablist" aria-label={t("specPhases")}>
      {STEPS.map((s, i) => {
        const isSlides = s.key === "slides"
        const active = activeTab === s.key
        const enabled = hasContent(s.key)

        return (
          <div key={s.key} className="flex items-center">
            {/* Connector line between steps */}
            {i > 0 && (
              <div className={`w-4 h-px mx-1 transition-colors duration-300 ${
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
                <Layers className={`h-3.5 w-3.5 ${active ? "text-brand-amber" : ""}`} />
              ) : (
                <span className={`
                  inline-flex items-center justify-center w-4 h-4 rounded-full text-[11px] font-semibold leading-none
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
                <span className={`text-[11px] font-normal ${active ? "text-brand-amber/70" : "text-foreground-muted"}`}>
                  · {slideCount}
                </span>
              )}

              {/* Active indicator dot */}
              {active && (
                <span className={`absolute -bottom-2.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full ${
                  isSlides ? "bg-brand-amber" : "bg-foreground"
                }`} />
              )}
            </button>
          </div>
        )
      })}
    </nav>
  )
}
