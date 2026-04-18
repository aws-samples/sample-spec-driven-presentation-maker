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
import { CustomizeMenu } from "@/components/deck/CustomizeMenu"
import { Search, X, Plus, Lock, Star, Users, Building2, Sparkles } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"

/** Tab definition for the list view. */
interface Tab {
  key: string
  label: string
  icon: typeof Lock
}

/** Available tabs in the deck list. */
const TABS: Tab[] = [
  { key: "mine", label: "My Decks", icon: Lock },
  { key: "favorites", label: "Favorites", icon: Star },
  { key: "shared", label: "Shared", icon: Users },
  { key: "public", label: "Internal", icon: Building2 },
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
  favoriteIds: Set<string>
  onToggleFavorite: (deckId: string, action: "add" | "remove") => void
  onDelete: (deckId: string) => void
  onToggleVisibility?: (deckId: string, visibility: "public" | "private") => void
  onShare?: (deckId: string) => void
  onDownload?: (deckId: string) => void
  loading: boolean
  onNewStyle?: () => void
  onUploadTemplate?: () => void
  onMyStyles?: () => void
  onMyTemplates?: () => void
}

export function DeckListView({
  decks, activeTab, onTabChange, searchQuery, onSearchChange,
  searchResults, searching, onDeckOpen, onNewDeck, favoriteIds,
  onToggleFavorite, onDelete, onToggleVisibility, onShare, onDownload, loading,
  onNewStyle, onUploadTemplate, onMyStyles, onMyTemplates,
}: DeckListViewProps) {
  const showSearch = searchQuery.length >= 2

  return (
    <div className="max-w-5xl mx-auto px-5 sm:px-8 py-8 sm:py-12">
      {/* Title + actions */}
      <div className="animate-card-in flex items-end justify-between mb-10">
        <div>
          <h1 className="text-[36px] sm:text-[42px] font-extrabold tracking-[-0.04em] leading-[1]">
            Decks
          </h1>
          <p className="text-[13px] text-foreground-muted mt-2.5 font-medium tracking-wide uppercase">
            {decks.length} {decks.length === 1 ? "presentation" : "presentations"}
          </p>
        </div>
        <div className="hidden sm:flex items-center gap-2">
          {onNewStyle && onUploadTemplate && onMyStyles && onMyTemplates && (
            <CustomizeMenu
              onNewStyle={onNewStyle}
              onUploadTemplate={onUploadTemplate}
              onMyStyles={onMyStyles}
              onMyTemplates={onMyTemplates}
            />
          )}
          <button
            onClick={onNewDeck}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-[12px] font-semibold rounded-lg bg-brand-teal text-primary-foreground transition-all hover:brightness-110"
          >
            <Plus className="h-3.5 w-3.5" />
            New Deck
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="animate-card-in search-glow relative mb-7 rounded-xl border border-border bg-background-raised" style={{ "--delay": "50ms" } as React.CSSProperties}>
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-foreground-muted" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") onSearchChange("") }}
          placeholder="Search slides across the organization…"
          className="w-full pl-11 pr-10 py-3 text-[13px] bg-transparent focus:outline-none placeholder:text-foreground-muted tracking-[-0.01em]"
        />
        {searchQuery && (
          <button
            onClick={() => onSearchChange("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-background-hover text-foreground-muted transition-all"
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Search results OR Tabs + Cards */}
      {showSearch ? (
        <SearchResultsGrid
          results={searchResults || []}
          searching={searching || false}
          onSlideClick={(deckId, slideId) => onDeckOpen(`${deckId}?slide=${slideId}`)}
        />
      ) : (
        <>
          {/* Tabs */}
          <div className="animate-card-in flex gap-0 mb-8 border-b border-border" style={{ "--delay": "100ms" } as React.CSSProperties}>
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => onTabChange(tab.key)}
                className={`relative flex items-center gap-1.5 px-4 py-2.5 text-[12px] font-medium transition-colors ${
                  activeTab === tab.key
                    ? "text-foreground"
                    : "text-foreground-muted hover:text-foreground-secondary"
                }`}
              >
                <tab.icon className="h-3 w-3" />
                {tab.label}
                <span
                  className="absolute bottom-0 left-0 right-0 h-[2px] transition-transform duration-300 origin-left"
                  style={{
                    background: "oklch(0.75 0.14 185)",
                    transform: activeTab === tab.key ? "scaleX(1)" : "scaleX(0)",
                  }}
                />
              </button>
            ))}
          </div>

          {/* Card grid */}
          {loading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-xl overflow-hidden border border-border bg-card">
                  <Skeleton className="aspect-[16/9.5] rounded-none" />
                  <div className="px-3.5 py-3 space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : decks.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title={activeTab === "mine" ? "No decks yet" : `No ${TABS.find(t => t.key === activeTab)?.label.toLowerCase() || "decks"} yet`}
              description={activeTab === "mine"
                ? "Create your first presentation with AI assistance."
                : "When decks appear here, you'll see them in this tab."
              }
              actionLabel={activeTab === "mine" ? "Create your first deck" : undefined}
              onAction={activeTab === "mine" ? onNewDeck : undefined}
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {decks.map((deck, i) => (
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
                  onShare={onShare}
                  onDownload={onDownload}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
