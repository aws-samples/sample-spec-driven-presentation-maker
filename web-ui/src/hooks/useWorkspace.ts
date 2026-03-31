// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useWorkspace — Manages workspace state: active deck, polling, hash routing.
 *
 * Extracted from decks/page.tsx to reduce God Component complexity.
 *
 * @param idToken - Cognito ID token for API calls
 * @param isAuthenticated - Whether the user is authenticated
 * @returns Workspace state and navigation callbacks
 */

"use client"

import { useEffect, useState, useRef, useCallback } from "react"
import { getDeck, DeckDetail } from "@/services/deckService"
import { ChatTabKey } from "@/components/chat/ChatPanelShell"

/** Extract deckId from hash, stripping any path prefix like "decks/" and query params. */
function parseDeckIdFromHash(hash: string): string {
  const raw = hash.replace("#", "").split("?")[0]
  return raw.replace(/^decks\//, "") || ""
}

/** Extract slide= param from hash if present. */
function parseSlideFromHash(hash: string): string {
  const match = hash.match(/[?&]slide=([^&]+)/)
  return match ? match[1] : ""
}

export function useWorkspace(
  idToken: string | undefined,
  isAuthenticated: boolean,
) {
  const [deck, setDeck] = useState<DeckDetail | null>(null)
  const [createdDeckId, setCreatedDeckId] = useState<string | null>(null)
  const [pptxRequested, setPptxRequested] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [chatTab, setChatTab] = useState<ChatTabKey>("new")
  const [scrollToSlide, setScrollToSlide] = useState<string>("")

  /* ── Hash routing ── */
  const initialHash = useRef(
    typeof window !== "undefined" ? parseDeckIdFromHash(window.location.hash) : ""
  )
  const [activeDeckId, setActiveDeckId] = useState<string | null>(
    initialHash.current || null
  )

  // Restore hash if cleared externally (e.g. OIDC library)
  useEffect(() => {
    if (activeDeckId && !window.location.hash) {
      window.history.replaceState(null, "", `#${activeDeckId}`)
    }
  }, [activeDeckId])

  useEffect(() => {
    const onHashChange = () => {
      const deckId = parseDeckIdFromHash(window.location.hash)
      if (deckId) setActiveDeckId(deckId)
    }
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  /* ── Data loading: workspace polling with exponential backoff ── */
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevSlideKeyRef = useRef<string>("")

  useEffect(() => {
    // Clear stale deck when switching to a different deck or entering "new" mode
    const deckIdToLoad = activeDeckId === "new" ? createdDeckId : activeDeckId
    if (!activeDeckId) {
      setDeck(null)
      return
    }
    if (activeDeckId === "new" && !createdDeckId) {
      // "new" deck with no ID yet — show blank state immediately
      setDeck(null)
      return
    }
    setDeck((prev) => {
      if (!prev) return prev
      const prevId = prev.deckId
      if (deckIdToLoad && prevId !== deckIdToLoad) return null
      return prev
    })

    /** Backoff intervals: 1s → 2s → 4s → 6s (then stay at 6s). */
    const INTERVALS = [1000, 2000, 4000, 6000]
    let step = 0

    async function poll() {
      if (!idToken || !deckIdToLoad || deckIdToLoad === "__polling__") {
        scheduleNext()
        return
      }
      try {
        const data = await getDeck(deckIdToLoad, idToken)
        // Detect slide changes (new slides or new PNGs) → reset backoff
        const slideKey = data.slides.map((s) => `${s.slideId}:${s.previewUrl || ""}`).join("|")
        if (slideKey !== prevSlideKeyRef.current) {
          prevSlideKeyRef.current = slideKey
          step = 0 // reset to fast polling on change
        }
        setDeck(data)
      } catch {
        // Deck may not exist yet
      }
      scheduleNext()
    }

    function scheduleNext() {
      const delay = INTERVALS[Math.min(step, INTERVALS.length - 1)]
      step++
      pollTimeoutRef.current = setTimeout(poll, delay)
    }

    if (isAuthenticated) {
      prevSlideKeyRef.current = ""
      poll() // immediate first fetch
    }

    return () => {
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current)
    }
  }, [isAuthenticated, idToken, activeDeckId, createdDeckId])

  /* ── Navigation callbacks ── */
  const navigateToList = useCallback(() => {
    setActiveDeckId(null)
    setChatTab("new")
    window.location.hash = ""
  }, [])

  const openDeck = useCallback((deckIdOrHash: string) => {
    const slideId = parseSlideFromHash("?" + deckIdOrHash.split("?")[1] || "")
    const deckId = deckIdOrHash.split("?")[0]
    window.location.hash = deckId
    setScrollToSlide(slideId)
    setChatOpen(true)
    setChatTab("deck")
  }, [])

  const handleDeckCreated = useCallback((signal: string) => {
    if (createdDeckId === signal) return
    setCreatedDeckId(signal)
    window.location.hash = signal
    setChatTab("deck")
  }, [createdDeckId])

  /* ── Derived state ── */
  const isWorkspace = activeDeckId !== null
  const isNew = activeDeckId === "new"
  const isOwner = deck?.role === "owner" || deck?.role === undefined
  const canChat = isOwner || isNew
  const hasSlides = deck && deck.slides.some((s) => s.previewUrl)
  const waitingForPng = pptxRequested

  // Reset flag once PNGs change after generate_pptx
  const prevSlideCountRef = useRef(0)
  useEffect(() => {
    const count = deck?.slides.filter((s) => s.previewUrl).length ?? 0
    if (pptxRequested && count > 0 && count !== prevSlideCountRef.current) {
      setPptxRequested(false)
    }
    prevSlideCountRef.current = count
  }, [pptxRequested, deck?.slides])

  return {
    activeDeckId, deck, setDeck, createdDeckId,
    chatOpen, setChatOpen, chatTab, setChatTab,
    isWorkspace, isNew, isOwner, canChat, hasSlides, waitingForPng,
    navigateToList, openDeck, handleDeckCreated, setPptxRequested,
    scrollToSlide, setScrollToSlide,
  }
}
