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
import { isHtmlPreview, previewIdentity } from "@/lib/preview"

/**
 * HTML deck URLs are 15-minute S3 presigned URLs. A stabilised URL is swapped for
 * the fresh one after this age (same file, new signature) so a frame that mounts
 * later never gets an expired link; mounted frames ignore the swap (identity is
 * unchanged), so nothing reloads.
 */
const HTML_URL_REFRESH_MS = 10 * 60 * 1000

type StableUrl = { url: string; at: number }

/**
 * Keep `cached` while it points at the same file, so a re-signed URL does not
 * re-download anything; take `fresh` when the file changed (or, for HTML URLs,
 * when the cached signature is getting old).
 */
function stabilise(cache: Map<string, StableUrl>, key: string, fresh: string): string {
  const cached = cache.get(key)
  const now = Date.now()
  const sameFile = cached != null && previewIdentity(cached.url) === previewIdentity(fresh)
  const stale = cached != null && isHtmlPreview(fresh) && now - cached.at > HTML_URL_REFRESH_MS
  if (sameFile && !stale) return cached.url
  cache.set(key, { url: fresh, at: now })
  return fresh
}

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
  const stablePreviewUrls = useRef<Map<string, StableUrl>>(new Map())
  const prevDeckSnapshotRef = useRef<string>("")

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

    let cancelled = false

    async function poll() {
      if (cancelled || !idToken || !deckIdToLoad || deckIdToLoad === "__polling__") {
        if (!cancelled) scheduleNext()
        return
      }
      try {
        const data = await getDeck(deckIdToLoad, idToken)
        if (cancelled) return
        // Detect slide changes (added/removed/preview updated)
        const slideKey = data.slides.map((s) => {
          const base = s.previewUrl ? previewIdentity(s.previewUrl) : ""
          return `${s.slug}:${base}`
        }).join("|")
        if (slideKey !== prevSlideKeyRef.current) {
          prevSlideKeyRef.current = slideKey
          step = 0 // reset to fast polling on change
        }
        // Stabilise presigned URLs to prevent unnecessary image re-downloads.
        // Update cache when the underlying S3 key changes (epoch in path).
        const cache = stablePreviewUrls.current
        for (const s of data.slides) {
          if (s.previewUrl) {
            s.previewUrl = stabilise(cache, s.slug, s.previewUrl)
          } else {
            cache.delete(s.slug)
          }
          // Stabilise composeUrl with same pattern as previewUrl
          if (s.composeUrl) s.composeUrl = stabilise(cache, `${s.slug}:compose`, s.composeUrl)
        }
        // Stabilise defsUrl and (HTML decks) the in-app view URL
        if (data.defsUrl) data.defsUrl = stabilise(cache, "__defs__", data.defsUrl)
        if (data.htmlUrl) data.htmlUrl = stabilise(cache, "__html__", data.htmlUrl)
        // Skip the state update when nothing changed — URLs are stabilised
        // above, so an identical snapshot means an identical render. Polling
        // runs every 1-6s; without this every poll re-renders the carousel.
        // Note: string comparison assumes the API returns keys in a stable
        // order (same endpoint, same serializer). A key-order change would
        // only cause an extra render, never a missed update.
        const snapshot = JSON.stringify(data)
        if (snapshot !== prevDeckSnapshotRef.current) {
          prevDeckSnapshotRef.current = snapshot
          setDeck(data)
        }
      } catch {
        // Deck may not exist yet
      }
      if (!cancelled) scheduleNext()
    }

    function scheduleNext() {
      const delay = INTERVALS[Math.min(step, INTERVALS.length - 1)]
      step++
      pollTimeoutRef.current = setTimeout(poll, delay)
    }

    if (isAuthenticated) {
      prevSlideKeyRef.current = ""
      prevDeckSnapshotRef.current = ""
      stablePreviewUrls.current.clear()
      poll() // immediate first fetch
    }

    return () => {
      cancelled = true
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
    const slug = parseSlideFromHash("?" + deckIdOrHash.split("?")[1] || "")
    const deckId = deckIdOrHash.split("?")[0]
    window.location.hash = deckId
    setScrollToSlide(slug)
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
  const hasSlides = deck && deck.slides.some((s) => s.previewUrl || s.composeUrl)
  const waitingForPng = pptxRequested

  // Reset flag once previews change after generate_pptx
  const prevPngKeyRef = useRef<string>("")
  useEffect(() => {
    if (!pptxRequested || !deck?.slides) return
    const pngKey = deck.slides.map((s) => `${s.slug}:${s.previewUrl ? previewIdentity(s.previewUrl) : ""}`).join("|")
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
