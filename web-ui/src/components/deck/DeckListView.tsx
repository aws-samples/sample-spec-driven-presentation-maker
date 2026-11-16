// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * DeckListView — Deck list page content with title, search, tabs, and card grid.
 *
 * Extracted from the God Component (decks/page.tsx) to isolate list view
 * concerns. Receives all data and callbacks from the parent page component.
 * When searchQuery has 2+ characters, shows SearchResultsGrid instead of tabs/cards.
 *
 * @param props.decks - Array of deck summaries for the active tab
 * @param props.activeTab - Currently selected tab key
 * @param props.onTabChange - Callback when tab is changed
 * @param props.searchQuery - Current search input value
 * @param props.onSearchChange - Callback when search input changes
 * @param props.searchResults - Slide search results (shown when searchQuery >= 2 chars)
 * @param props.searching - Whether slide search is in progress
 * @param props.onDeckOpen - Callback when a deck card is clicked
 * @param props.onNewDeck - Callback to start creating a new deck
 * @param props.favoriteIds - Set of deck IDs favorited by current user
 * @param props.onToggleFavorite - Callback to toggle favorite status
 * @param props.onDelete - Callback to delete a deck
 * @param props.loading - Whether deck list is loading
 */

"use client"

import { DeckSummary, SlideSearchResult } from "@/services/deckService"
import { DeckCard } from "@/components/deck/DeckCard"
import { EmptyState } from "@/components/deck/EmptyState"
import { SearchResultsGrid } from "@/components/deck/SearchResultsGrid"
import { SelectionBar } from "@/components/deck/SelectionBar"
import { Search, X, Lock, Star, Building2, Sparkles, CheckSquare, ArrowUp } from "lucide-react"
import { useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { IS_LOCAL } from "@/lib/mode"
import { useTranslations } from "next-intl"

/** Tab definition for the list view. labelKey resolves via deckList.tabs.* */
interface Tab {
  key: string
  labelKey: "mine" | "favorites" | "public"
  icon: typeof Lock
}

/** Available tabs in the deck list. */
const TABS: Tab[] = IS_LOCAL ? [] : [
  { key: "mine", labelKey: "mine", icon: Lock },
  { key: "favorites", labelKey: "favorites", icon: Star },
  { key: "public", labelKey: "public", icon: Building2 },
]

interface DeckListViewProps {
  decks: DeckSummary[]
  activeTab: string
  onTabChange: (tab: string) => void
  searchQuery: string
  onSearchChange: (query: string) => void
  searchResults?: SlideSearchResult[]
  searching?: boolean
  onDeckOpen: (deckId: string) => void
  onNewDeck: () => void
  /** Start a new deck from the home prompt. Falls back to onNewDeck when absent. */
  onCreateWithPrompt?: (prompt: string) => void
  favoriteIds: Set<string>
  onToggleFavorite: (deckId: string, action: "add" | "remove") => void
  onDelete: (deckId: string) => void
  onToggleVisibility?: (deckId: string, visibility: "public" | "private") => void
  onDownload?: (deckId: string) => void
  onOpenPptx?: (deckId: string) => void
  onOpenFolder?: (deckId: string) => void
  loading: boolean
  /** Multi-select (bulk delete). Provided only when the active tab allows it. */
  selection?: {
    selectionMode: boolean
    selectedIds: Set<string>
    enter: () => void
    exit: () => void
    toggle: (deckId: string, shiftKey: boolean) => void
    selectAll: () => void
    onDeleteSelected: () => void
    progress: { done: number; total: number } | null
  }
}

/**
 * Decks actually rendered as cards. Local mode has no server-side slide search,
 * so the query filters deck names client-side instead.
 */
export function visibleDecks(decks: DeckSummary[], searchQuery: string): DeckSummary[] {
  if (!IS_LOCAL || !searchQuery) return decks
  const q = searchQuery.toLowerCase()
  return decks.filter(d => (d.name || "").toLowerCase().includes(q))
}

export function DeckListView({
  decks, activeTab, onTabChange, searchQuery, onSearchChange,
  searchResults, searching, onDeckOpen, onNewDeck, onCreateWithPrompt, favoriteIds,
  onToggleFavorite, onDelete, onToggleVisibility, onDownload, onOpenPptx, onOpenFolder, loading,
  selection,
}: DeckListViewProps) {
  const t = useTranslations("deckList")
  const showSearch = !IS_LOCAL && searchQuery.length >= 2
  const filteredDecks = visibleDecks(decks, searchQuery)
  const canSelect = !!selection && activeTab === "mine" && !showSearch && filteredDecks.length > 0
  const selecting = canSelect && selection.selectionMode

  const [prompt, setPrompt] = useState("")
  const submitPrompt = () => {
    const text = prompt.trim()
    if (text && onCreateWithPrompt) { onCreateWithPrompt(text); setPrompt("") }
    else onNewDeck()
  }

  return (
    <div className={`max-w-6xl mx-auto px-5 sm:px-10 pt-12 sm:pt-20 pb-12 ${selecting ? "pb-28" : ""}`}>
      {/* ── Hero: creating a deck starts here ── */}
      <section className="animate-card-in max-w-[720px] mx-auto mb-16 sm:mb-24">
        <h1 className="text-center text-3xl sm:text-5xl font-semibold tracking-[-0.035em] leading-[1.15] text-balance">
          {t("heroTitle")}
        </h1>
        <p className="text-center text-[15px] text-foreground-secondary mt-3 text-balance">
          {t("heroSubtitle")}
        </p>
        <form
          onSubmit={(e) => { e.preventDefault(); submitPrompt() }}
          className="hero-prompt mt-9 rounded-2xl border border-border-hover bg-background-raised shadow-[var(--shadow-card)]"
        >
          <label htmlFor="hero-prompt" className="sr-only">{t("heroTitle")}</label>
          <textarea
            id="hero-prompt"
            rows={3}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submitPrompt() }
            }}
            placeholder={t("heroPlaceholder")}
            className="block w-full resize-none bg-transparent px-5 pt-4 pb-1 text-[15px] leading-relaxed outline-none placeholder:text-foreground-muted"
          />
          <div className="flex items-center justify-between gap-3 px-3 pb-3 pt-1">
            <span className="pl-2 text-xs text-foreground-muted">{t("heroHint")}</span>
            <button
              type="submit"
              className="team-action-btn team-entry-btn inline-flex items-center gap-1.5 h-9 pl-4 pr-3 text-sm font-semibold rounded-xl transition-all"
            >
              {t("heroSubmit")}
              <ArrowUp className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </form>
      </section>

      {/* ── Library ── */}
      <div className="animate-card-in flex flex-wrap items-center justify-between gap-3 mb-6" style={{ "--delay": "50ms" } as React.CSSProperties}>
        <div className="flex items-baseline gap-3">
          <h2 className="text-xl font-semibold tracking-[-0.025em]">{t("title")}</h2>
          <span className="text-sm text-foreground-muted">{t("presentationCount", { count: decks.length })}</span>
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="search-glow relative flex-1 sm:w-72 rounded-lg border border-border bg-background-raised">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-foreground-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Escape") onSearchChange("") }}
              placeholder={IS_LOCAL ? t("searchPlaceholderLocal") : t("searchPlaceholder")}
              aria-label={IS_LOCAL ? t("searchPlaceholderLocal") : t("searchPlaceholder")}
              className="w-full h-9 pl-9 pr-8 text-sm bg-transparent focus:outline-none placeholder:text-foreground-muted"
            />
            {searchQuery && (
              <button
                onClick={() => onSearchChange("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-background-hover text-foreground-muted transition-all"
                aria-label={t("clearSearch")}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          {canSelect && (
            <button
              type="button"
              onClick={() => (selecting ? selection.exit() : selection.enter())}
              aria-pressed={selecting}
              className="hidden sm:inline-flex items-center gap-1.5 h-9 px-3 text-sm font-medium rounded-lg border border-border text-foreground-secondary hover:text-foreground hover:bg-background-hover transition-colors"
            >
              <CheckSquare className="h-3.5 w-3.5" aria-hidden="true" />
              {selecting ? t("cancelSelection") : t("select")}
            </button>
          )}
        </div>
      </div>

      {/* Search results OR Tabs + Cards */}
      {showSearch ? (
        <SearchResultsGrid
          results={searchResults || []}
          searching={searching || false}
          onSlideClick={(deckId, slug) => onDeckOpen(`${deckId}?slide=${slug}`)}
        />
      ) : (
        <>
          {/* Tabs */}
          <div className={`animate-card-in flex gap-0 mb-8 border-b border-border ${TABS.length ? "" : "hidden"}`} style={{ "--delay": "100ms" } as React.CSSProperties}>
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => onTabChange(tab.key)}
                className={`relative flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? "text-foreground"
                    : "text-foreground-muted hover:text-foreground-secondary"
                }`}
              >
                <tab.icon className="h-3 w-3" />
                {t(`tabs.${tab.labelKey}`)}
                <span
                  className="absolute bottom-0 left-0 right-0 h-[2px] transition-transform duration-300 origin-left bg-foreground"
                  style={{
                    transform: activeTab === tab.key ? "scaleX(1)" : "scaleX(0)",
                  }}
                />
              </button>
            ))}
          </div>

          {/* Card grid */}
          {loading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-9">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i}>
                  <Skeleton className="aspect-video rounded-lg" />
                  <div className="pt-3 space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : filteredDecks.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title={activeTab === "mine" ? t("emptyMineTitle") : t("emptyOtherTitle", { tab: t(`tabs.${TABS.find(tb => tb.key === activeTab)?.labelKey || "mine"}`) })}
              description={activeTab === "mine" ? t("emptyMineDescription") : t("emptyOtherDescription")}
              actionLabel={activeTab === "mine" ? t("emptyMineAction") : undefined}
              onAction={activeTab === "mine" ? onNewDeck : undefined}
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-9">
              {filteredDecks.map((deck, i) => (
                <DeckCard
                  key={deck.deckId}
                  deck={deck}
                  index={i}
                  isFavorite={favoriteIds.has(deck.deckId)}
                  isOwner={activeTab === "mine"}
                  onOpen={onDeckOpen}
                  onToggleFavorite={onToggleFavorite}
                  onDelete={onDelete}
                  onToggleVisibility={onToggleVisibility}
                  onDownload={onDownload}
                  onOpenPptx={onOpenPptx}
                  onOpenFolder={onOpenFolder}
                  selectable={canSelect}
                  selectionMode={selecting}
                  selected={canSelect && selection.selectedIds.has(deck.deckId)}
                  onSelectToggle={canSelect ? selection.toggle : undefined}
                />
              ))}
            </div>
          )}
        </>
      )}

      {selecting && (
        <SelectionBar
          count={selection.selectedIds.size}
          total={filteredDecks.length}
          progress={selection.progress}
          onSelectAll={selection.selectAll}
          onDelete={selection.onDeleteSelected}
          onCancel={selection.exit}
        />
      )}
    </div>
  )
}
