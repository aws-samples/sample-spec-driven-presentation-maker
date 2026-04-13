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
  const pptxRequestedRef = useRef(false)
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
  const stablePreviewUrls = useRef<Map<string, { url: string }>>(new Map())

  // Clear URL cache when switching decks
  useEffect(() => {
    pptxRequestedRef.current = pptxRequested
  }, [pptxRequested])

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
        // Detect slide changes (added/removed/preview updated)
        const slideKey = data.slides.map((s) => {
          const base = s.previewUrl?.split("?")[0] || ""
          return `${s.slideId}:${base}`
        }).join("|")
        if (slideKey !== prevSlideKeyRef.current) {
          prevSlideKeyRef.current = slideKey
          step = 0 // reset to fast polling on change
        }
        // Stabilise presigned URLs to prevent unnecessary image re-downloads.
        // Update cache when the underlying S3 key changes (epoch in path).
        for (const s of data.slides) {
          if (s.previewUrl) {
            const cached = stablePreviewUrls.current.get(s.slideId)
            const stableKey = (slide: typeof s) => {
              return slide.previewUrl?.split("?")[0] || ""
            }
            if (stableKey(s) !== (cached ? stableKey({ previewUrl: cached.url } as typeof s) : "")) {
              stablePreviewUrls.current.set(s.slideId, { url: s.previewUrl })
            } else if (cached) {
              s.previewUrl = cached.url
            }
          } else {
            stablePreviewUrls.current.delete(s.slideId)
          }
          // Stabilise composeUrl with same pattern
          if (s.composeUrl) {
            const cacheKey = `${s.slideId}:compose`
            const cached = stablePreviewUrls.current.get(cacheKey)
            const base = s.composeUrl.split("?")[0]
            const cachedBase = cached?.url.split("?")[0] || ""
            if (base !== cachedBase) {
              stablePreviewUrls.current.set(cacheKey, { url: s.composeUrl })
            } else if (cached) {
              s.composeUrl = cached.url
            }
          }
        }
        // Stabilise defsUrl
        if (data.defsUrl) {
          const cached = stablePreviewUrls.current.get("__defs__")
          const base = data.defsUrl.split("?")[0]
          const cachedBase = cached?.url.split("?")[0] || ""
          if (base !== cachedBase) {
            stablePreviewUrls.current.set("__defs__", { url: data.defsUrl })
          } else if (cached) {
            data.defsUrl = cached.url
          }
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
      stablePreviewUrls.current.clear()
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

  // Reset flag once previews change after generate_pptx
  const prevPngKeyRef = useRef<string>("")
  useEffect(() => {
    if (!pptxRequested || !deck?.slides) return
    const pngKey = deck.slides.map((s) => `${s.slideId}:${s.previewUrl?.split("?")[0] || ""}`).join("|")
    if (prevPngKeyRef.current && pngKey !== prevPngKeyRef.current) {
      setPptxRequested(false)
    }
    prevPngKeyRef.current = pngKey
  }, [pptxRequested, deck?.slides])

  return {
    activeDeckId, deck, setDeck, createdDeckId,
    chatOpen, setChatOpen, chatTab, setChatTab,
    isWorkspace, isNew, isOwner, canChat, hasSlides, waitingForPng,
    navigateToList, openDeck, handleDeckCreated, setPptxRequested,
    scrollToSlide, setScrollToSlide,
  }
}
