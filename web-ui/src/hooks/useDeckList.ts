// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useDeckList — Manages deck list state: fetching, tabs, search, favorites, and actions.
 *
 * Extracted from decks/page.tsx to reduce God Component complexity.
 *
 * @param idToken - Cognito ID token for API calls
 * @param isAuthenticated - Whether the user is authenticated
 * @param activeDeckId - Current active deck ID (null when on list view)
 * @returns Deck list state and action callbacks
 */

"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { IS_LOCAL } from "@/lib/mode"
import {
  listDecks, DeckSummary,
  listPublicDecks, listSharedDecks, listFavorites,
  updateVisibility, deleteDeck, toggleFavorite,
  searchSlides, SlideSearchResult,
} from "@/services/deckService"
import { toast } from "sonner"
import { notifyError } from "@/lib/errors"

/** Parallel DELETE calls during a bulk delete. */
const BULK_DELETE_CONCURRENCY = 5

export function useDeckList(
  idToken: string | undefined,
  isAuthenticated: boolean,
  activeDeckId: string | null,
) {
  const [decks, setDecks] = useState<DeckSummary[]>([])
  const [publicDecks, setPublicDecks] = useState<DeckSummary[]>([])
  const [sharedDecks, setSharedDecks] = useState<DeckSummary[]>([])
  const [favoriteDecks, setFavoriteDecks] = useState<DeckSummary[]>([])
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set())
  const [activeListTab, setActiveListTab] = useState<"mine" | "favorites" | "public" | "shared">("mine")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DeckSummary | null>(null)
  const [bulkDeleteTargets, setBulkDeleteTargets] = useState<DeckSummary[] | null>(null)
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<SlideSearchResult[]>([])
  const [searching, setSearching] = useState(false)

  /** Fetch all deck lists when on list view. */
  const initialLoadDone = useRef(false)
  useEffect(() => {
    if (activeDeckId !== null) return
    if (!isAuthenticated || !idToken) return

    async function load() {
      try {
        const [myData, pubDecks, shDecks, favDecks] = await Promise.all([
          listDecks(idToken!),
          listPublicDecks(idToken!),
          listSharedDecks(idToken!),
          listFavorites(idToken!),
        ])
        // Merge: preserve existing thumbnailUrl if deckId matches to avoid image flicker
        setDecks((prev) => {
          const prevMap = new Map(prev.map((d) => [d.deckId, d]))
          return myData.decks.map((d) => {
            const existing = prevMap.get(d.deckId)
            if (existing && existing.thumbnailUrl && d.thumbnailUrl) {
              return { ...d, thumbnailUrl: existing.thumbnailUrl }
            }
            return d
          })
        })
        setFavoriteIds(new Set(myData.favoriteIds))
        setPublicDecks(pubDecks)
        setSharedDecks(shDecks)
        setFavoriteDecks(favDecks)
      } catch (err) {
        if (!initialLoadDone.current) {
          setError(err instanceof Error ? err.message : "Failed to load decks")
        }
      } finally {
        initialLoadDone.current = true
        setLoading(false)
      }
    }

    load()
  }, [isAuthenticated, idToken, activeDeckId])

  /** Debounced slide search. */
  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults([])
      return
    }
    if (!idToken) return

    setSearching(true)
    const timer = setTimeout(async () => {
      const results = await searchSlides(searchQuery, idToken)
      setSearchResults(results)
      setSearching(false)
    }, 300)
    return () => { clearTimeout(timer); setSearching(false) }
  }, [searchQuery, idToken])

  const handleToggleFavorite = useCallback(async (deckId: string, action: "add" | "remove") => {
    if (!idToken) return
    const prev = favoriteIds
    const next = new Set(favoriteIds)
    if (action === "add") next.add(deckId); else next.delete(deckId)
    setFavoriteIds(next)
    try {
      await toggleFavorite(deckId, action, idToken)
      const favs = await listFavorites(idToken)
      setFavoriteDecks(favs)
    } catch {
      setFavoriteIds(prev)
    }
  }, [idToken, favoriteIds])

  const handleDelete = useCallback((deckId: string) => {
    const target = decks.find((d) => d.deckId === deckId)
    if (target) setDeleteTarget(target)
  }, [decks])

  const handleToggleVisibility = useCallback(async (deckId: string, visibility: "public" | "private") => {
    if (!idToken) return
    try {
      await updateVisibility(deckId, visibility, idToken)
      setDecks((prev) => prev.map((d) => d.deckId === deckId ? { ...d, visibility } : d))
    } catch {
      toast.error("Failed to update visibility.")
    }
  }, [idToken])

  const handleDownload = useCallback((deckId: string) => {
    const target = decks.find((d) => d.deckId === deckId)
    if (!target?.pptxUrl) return
    if (IS_LOCAL) {
      fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deckId, file: "output.pptx" }) }).catch((err) => notifyError("Failed to open PPTX", err))
    } else {
      window.open(target.pptxUrl, "_blank")
    }
  }, [decks])

  const handleOpenFolder = useCallback((deckId: string) => {
    if (!IS_LOCAL) return
    fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deckId }) }).catch((err) => notifyError("Failed to open deck folder", err))
  }, [])

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget || !idToken) return
    try {
      await deleteDeck(deleteTarget.deckId, idToken)
      setDecks((prev) => prev.filter((d) => d.deckId !== deleteTarget.deckId))
      setDeleteTarget(null)
    } catch {
      toast.error("Failed to delete deck.")
    }
  }, [deleteTarget, idToken])

  /** Bulk delete: ask for confirmation, then delete in parallel (bounded). */
  const requestBulkDelete = useCallback((deckIds: string[]) => {
    const wanted = new Set(deckIds)
    const targets = decks.filter((d) => wanted.has(d.deckId))
    if (targets.length) setBulkDeleteTargets(targets)
  }, [decks])

  const confirmBulkDelete = useCallback(async (): Promise<{ deleted: number; failed: number }> => {
    if (!bulkDeleteTargets || !idToken) return { deleted: 0, failed: 0 }
    const targets = bulkDeleteTargets
    const total = targets.length
    setBulkProgress({ done: 0, total })
    let failed = 0
    let done = 0
    // Bounded concurrency: keep API Gateway / KB cleanup load predictable.
    const queue = [...targets]
    async function worker() {
      for (let next = queue.shift(); next; next = queue.shift()) {
        const target = next
        try {
          await deleteDeck(target.deckId, idToken!)
          setDecks((prev) => prev.filter((d) => d.deckId !== target.deckId))
        } catch {
          failed += 1
        }
        done += 1
        setBulkProgress({ done, total })
      }
    }
    await Promise.all(Array.from({ length: Math.min(BULK_DELETE_CONCURRENCY, total) }, worker))
    setBulkProgress(null)
    setBulkDeleteTargets(null)
    return { deleted: total - failed, failed }
  }, [bulkDeleteTargets, idToken])

  /** Decks for the currently active list tab. */
  const tabDecks = activeListTab === "mine" ? decks
    : activeListTab === "favorites" ? favoriteDecks
    : activeListTab === "public" ? publicDecks
    : sharedDecks

  return {
    decks, tabDecks, favoriteIds, activeListTab, setActiveListTab,
    loading, error, deleteTarget, setDeleteTarget,
    bulkDeleteTargets, setBulkDeleteTargets, bulkProgress, requestBulkDelete, confirmBulkDelete,
    searchQuery, setSearchQuery, searchResults, searching,
    handleToggleFavorite, handleDelete, handleToggleVisibility, handleDownload, handleOpenFolder, confirmDelete,
    setDecks,
  }
}
