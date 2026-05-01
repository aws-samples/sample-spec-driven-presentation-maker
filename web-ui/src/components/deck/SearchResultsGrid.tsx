// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SearchResultsGrid — Slide search results displayed as a thumbnail grid.
 *
 * Shows matching slides from Bedrock KB semantic search with preview images,
 * deck name, owner alias, and page number. Includes loading skeleton and
 * empty state.
 *
 * @param props.results - Array of slide search results
 * @param props.searching - Whether search is in progress
 * @param props.onSlideClick - Callback when a search result is clicked (navigates to deck)
 */

"use client"

import { SlideSearchResult } from "@/services/deckService"
import { Skeleton } from "@/components/ui/skeleton"
import { Search, Layers } from "lucide-react"

interface SearchResultsGridProps {
  results: SlideSearchResult[]
  searching: boolean
  onSlideClick: (deckId: string, slug: string) => void
}

export function SearchResultsGrid({ results, searching, onSlideClick }: SearchResultsGridProps) {
  return (
    <>
      <p className="text-[12px] text-foreground-muted font-medium mb-4">
        {searching ? "Searching slides across the organization…" : `${results.length} result${results.length !== 1 ? "s" : ""} found`}
      </p>

      {searching ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="space-y-3">
              <Skeleton className="aspect-[16/9] rounded-xl" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))}
        </div>
      ) : results.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {results.map((r, i) => (
            <button
              key={`${r.deckId}-${r.slug}`}
              type="button"
              onClick={() => onSlideClick(r.deckId, r.slug)}
              className="animate-card-in group text-left rounded-xl overflow-hidden border border-border bg-card hover:border-border-hover hover:-translate-y-[2px] hover:shadow-[0_6px_24px_oklch(0_0_0/40%)] transition-all duration-300"
              style={{ "--delay": `${i * 60}ms` } as React.CSSProperties}
            >
              <div className="aspect-[16/9] bg-background-raised relative overflow-hidden">
                {r.previewUrl ? (
                  <img
                    src={r.previewUrl}
                    alt={`${r.deckName} page ${r.pageNumber}`}
                    className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-500 ease-out"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <Layers className="h-8 w-8 text-foreground-muted/20" />
                  </div>
                )}
              </div>
              <div className="px-4 py-3.5">
                <h3 className="text-[13px] font-medium text-foreground/90 truncate leading-snug">
                  {r.deckName || "Untitled"}
                </h3>
                <p className="text-[11px] text-foreground-muted mt-1 tracking-wide uppercase">
                  {r.ownerAlias}
                  <span className="mx-1.5 opacity-40">·</span>
                  Page {r.pageNumber}
                </p>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <Search className="h-8 w-8 text-foreground-muted/20 mb-4" />
          <p className="text-[13px] font-medium text-foreground/60 mb-1">No matching slides</p>
          <p className="text-[12px] text-foreground-muted">Try different keywords or a broader search term.</p>
        </div>
      )}
    </>
  )
}
