// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Read-only slide storyboard for an outline markdown document.
 *
 * The existing outline parser remains the source of slide, chapter, and prose
 * structure. The document H1 is derived separately because the parser
 * deliberately treats unknown markdown (including H1 lines) as prose.
 */

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import type { Ref, ReactElement, ReactNode } from "react"
import { FileText } from "lucide-react"
import { useTranslations } from "next-intl"
import { renderColorSwatches } from "./colorSwatches"
import { parseOutline, resolveStates } from "./outlineParser"
import type {
  OutlineEntry,
  ProseEntry,
  SectionEntry,
  SlideEntry,
  SlideState,
  SubItemKey,
} from "./outlineParser"

const LAYOUT_STORAGE_KEY = "sdpm-outline-layout"
const TBD_RE = /\[TBD(?::?\s*([^\]]*))?\]/g

type StoryboardLayout = "grid" | "column"

function readStoredLayout(): StoryboardLayout {
  if (typeof window === "undefined") return "grid"
  return localStorage.getItem(LAYOUT_STORAGE_KEY) === "column" ? "column" : "grid"
}

function getSubItemValue(slide: SlideEntry, key: SubItemKey): string {
  return slide.subItems
    .filter((item) => item.key === key)
    .map((item) => item.value)
    .join(" ")
}

/** Render outline values with existing color swatches and outlined TBD chips. */
function renderValue(value: string): (string | ReactElement)[] {
  const parts = value.split(TBD_RE)
  const elements: (string | ReactElement)[] = []

  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      if (parts[i]) elements.push(...renderColorSwatches(parts[i]))
      continue
    }

    const detail = parts[i]
    elements.push(
      <span key={`tbd-${i}`} className="storyboard-tbd">
        TBD{detail ? `: ${detail}` : ""}
      </span>
    )
  }

  return elements
}

function StoryboardSlide({
  slide,
  number,
  state,
  articleRef,
}: {
  slide: SlideEntry
  number: number
  state: SlideState
  articleRef?: Ref<HTMLElement>
}): ReactElement {
  const body = getSubItemValue(slide, "body")
  const visual = getSubItemValue(slide, "visual")
  const evidence = getSubItemValue(slide, "evidence")
  const isSkeleton = slide.subItems.length === 0

  return (
    <article
      ref={articleRef}
      className="storyboard-slide"
      data-slide-slug={slide.slug}
      data-state={state}
    >
      <span className="storyboard-slide-number" data-active={state === "active" || undefined}>
        {number}
      </span>
      <div className="storyboard-paper">
        <div className="storyboard-slug">{slide.slug}</div>
        <h3 className="storyboard-slide-title">{renderValue(slide.message || slide.slug)}</h3>
        <p className="storyboard-body">{renderValue(body)}</p>
        {!isSkeleton && (
          <footer className="storyboard-footer">
            <div>
              <b>VISUAL</b>
              <span>{renderValue(visual)}</span>
            </div>
            <div>
              <b>SRC</b>
              <span>{renderValue(evidence)}</span>
            </div>
          </footer>
        )}
      </div>
    </article>
  )
}

function ChapterDivider({
  section,
  number,
  slideCount,
  slideCountLabel,
}: {
  section: SectionEntry
  number: number
  slideCount: number
  slideCountLabel: string
}): ReactElement {
  return (
    <div className="storyboard-chapter" data-entry-type="section" data-slide-count={slideCount}>
      <span className="storyboard-chapter-number">{String(number).padStart(2, "0")}</span>
      <h2>{section.title}</h2>
      <span className="storyboard-chapter-count">{slideCountLabel}</span>
      <div className="storyboard-chapter-rule" aria-hidden="true" />
    </div>
  )
}

function ProseBlock({ entry }: { entry: ProseEntry }): ReactElement {
  return (
    <div className="storyboard-prose" data-entry-type="prose">
      <p>{renderColorSwatches(entry.text)}</p>
    </div>
  )
}

function chapterSlideCount(entries: OutlineEntry[], sectionIndex: number): number {
  let count = 0
  for (let i = sectionIndex + 1; i < entries.length; i++) {
    if (entries[i].type === "section") break
    if (entries[i].type === "slide") count++
  }
  return count
}

interface OutlineViewProps {
  content: string | null
}

export function OutlineView({ content }: OutlineViewProps): ReactElement {
  const t = useTranslations("outline")
  const activeRef = useRef<HTMLElement>(null)
  const prevActiveSlug = useRef<string | null>(null)
  const [layout, setLayout] = useState<StoryboardLayout>("grid")

  const { title, entries, stateMap } = useMemo(() => {
    if (!content) {
      return {
        title: null,
        entries: [] as OutlineEntry[],
        stateMap: new Map<number, SlideState>(),
      }
    }

    const titleMatch = content.match(/^#\s+(.+?)\s*$/m)
    const deckTitle = titleMatch?.[1].trim() ?? null
    let removedTitle = false
    const parsed = parseOutline(content).filter((entry) => {
      if (
        !removedTitle &&
        deckTitle &&
        entry.type === "prose" &&
        entry.text.match(/^#\s+(.+?)\s*$/)?.[1].trim() === deckTitle
      ) {
        removedTitle = true
        return false
      }
      return true
    })

    return {
      title: deckTitle,
      entries: parsed,
      stateMap: resolveStates(parsed),
    }
  }, [content])

  const activeSlug = useMemo(() => {
    for (const [index, state] of stateMap.entries()) {
      const entry = entries[index]
      if (state === "active" && entry.type === "slide") return entry.slug
    }
    return null
  }, [entries, stateMap])

  useEffect(() => {
    setLayout(readStoredLayout())
  }, [])

  useEffect(() => {
    if (activeSlug === null || activeSlug === prevActiveSlug.current) return
    prevActiveSlug.current = activeSlug
    const timer = setTimeout(() => {
      activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
    }, 150)
    return () => clearTimeout(timer)
  }, [activeSlug])

  const selectLayout = (nextLayout: StoryboardLayout) => {
    setLayout(nextLayout)
    localStorage.setItem(LAYOUT_STORAGE_KEY, nextLayout)
  }

  if (!content || (!title && entries.length === 0)) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-4">
          <FileText className="h-5 w-5 text-foreground-muted/30" />
        </div>
        <p className="text-sm text-foreground-muted">{t("emptyState")}</p>
      </div>
    )
  }

  const slideCount = entries.filter((entry) => entry.type === "slide").length
  const chapterCount = entries.filter((entry) => entry.type === "section").length
  const renderedEntries: ReactNode[] = []
  let chapterNumber = 0
  let slideNumber = 0
  let entryIndex = 0

  while (entryIndex < entries.length) {
    const entry = entries[entryIndex]

    if (entry.type === "section") {
      chapterNumber++
      const count = chapterSlideCount(entries, entryIndex)
      renderedEntries.push(
        <ChapterDivider
          key={`chapter-${entryIndex}`}
          section={entry}
          number={chapterNumber}
          slideCount={count}
          slideCountLabel={t("slideCount", { count })}
        />
      )
      entryIndex++
      continue
    }

    if (entry.type === "prose") {
      renderedEntries.push(<ProseBlock key={`prose-${entryIndex}`} entry={entry} />)
      entryIndex++
      continue
    }

    const slides: ReactNode[] = []
    while (entryIndex < entries.length && entries[entryIndex].type === "slide") {
      const slide = entries[entryIndex] as SlideEntry
      const state = stateMap.get(entryIndex) ?? "skeleton"
      const isActive = state === "active"
      slideNumber++
      slides.push(
        <StoryboardSlide
          key={`${slide.slug}-${entryIndex}`}
          slide={slide}
          number={slideNumber}
          state={state}
          articleRef={isActive ? activeRef : undefined}
        />
      )
      entryIndex++
    }
    renderedEntries.push(
      <section className="storyboard-slides" key={`slides-${entryIndex}`}>
        {slides}
      </section>
    )
  }

  return (
    <div className="document-surface storyboard-scroll flex-1 overflow-y-auto">
      <main
        className={`storyboard-view storyboard-layout-${layout}`}
        data-layout={layout}
      >
        <header className="storyboard-header">
          <div className="storyboard-title-block">
            {title && <h1>{title}</h1>}
            <p>
              {t("slideCount", { count: slideCount })}
              <span aria-hidden="true"> · </span>
              {t("chapterCount", { count: chapterCount })}
            </p>
          </div>
          <div className="storyboard-layout-toggle" role="group" aria-label={t("layoutLabel")}>
            <button
              type="button"
              aria-pressed={layout === "grid"}
              onClick={() => selectLayout("grid")}
            >
              {t("gridLayout")}
            </button>
            <button
              type="button"
              aria-pressed={layout === "column"}
              onClick={() => selectLayout("column")}
            >
              {t("columnLayout")}
            </button>
          </div>
        </header>
        {renderedEntries}
      </main>
    </div>
  )
}
