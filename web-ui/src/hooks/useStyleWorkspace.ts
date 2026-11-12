// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useStyleWorkspace — Hash routing for the /styles page.
 *
 * Mirrors useWorkspace (decks) but much simpler: no polling, no deck state.
 * Hash values: "" (list), "#/create" (new style), "#{name}" (preview). A style name
 * never holds "/", so every name, "create" included, has its own preview hash.
 *
 * Preview HTML is resolved from the preloaded styles array (passed via
 * setStyles) to eliminate the /styles/{name} fetch round-trip. Falls back to
 * fetchStylePreviewHtml only when the style is not in the preloaded set (e.g.
 * direct navigation via URL hash before the list has loaded).
 *
 * refreshPreview (the agent saved the style) always fetches: the preloaded array still holds
 * the style as it was before the save, so resolving from it showed every save one save late.
 * The current preview stays on screen until the new HTML arrives.
 */

"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { fetchStylePreviewHtml, type StyleEntry } from "@/services/deckService"

export type StyleView = { mode: "list" } | { mode: "preview"; name: string } | { mode: "create" }

const CREATE_HASH = "/create"

export function parseHash(hash: string): StyleView {
  const raw = hash.replace("#", "")
  if (!raw) return { mode: "list" }
  if (raw === CREATE_HASH) return { mode: "create" }
  return { mode: "preview", name: decodeURIComponent(raw) }
}

export function useStyleWorkspace(idToken: string | undefined) {
  const [view, setView] = useState<StyleView>(
    () => typeof window !== "undefined" ? parseHash(window.location.hash) : { mode: "list" }
  )
  const [previewHtml, setPreviewHtml] = useState("")
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewVersion, setPreviewVersion] = useState(0)
  const stylesRef = useRef<StyleEntry[]>([])
  /** Set by refreshPreview: the next resolve fetches instead of reading stylesRef. */
  const fetchNextRef = useRef(false)

  /** Provide the preloaded styles array so preview can resolve locally. */
  const setStyles = useCallback((styles: StyleEntry[]) => {
    stylesRef.current = styles
  }, [])

  // Sync hash → state
  useEffect(() => {
    const onHashChange = () => setView(parseHash(window.location.hash))
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  // Resolve preview HTML: prefer preloaded styles, fall back to fetch.
  useEffect(() => {
    if (view.mode !== "preview" || !idToken) { setPreviewHtml(""); return }

    const refreshing = fetchNextRef.current
    fetchNextRef.current = false

    // Try resolving from preloaded styles (instant, no round-trip)
    const cached = refreshing ? undefined : stylesRef.current.find(s => s.name === view.name)
    if (cached?.html) {
      setPreviewHtml(cached.html)
      setPreviewLoading(false)
      return
    }

    // Fetch from server: after a save, or before the list has loaded (direct URL navigation)
    let cancelled = false
    if (!refreshing) setPreviewLoading(true)
    fetchStylePreviewHtml(view.name, idToken).then(html => {
      if (cancelled) return
      // A failed refresh ("") keeps the preview that is on screen.
      if (html || !refreshing) setPreviewHtml(html)
      setPreviewLoading(false)
    })
    return () => { cancelled = true }
  }, [view, idToken, previewVersion])

  const refreshPreview = useCallback(() => {
    fetchNextRef.current = true
    setPreviewVersion(v => v + 1)
  }, [])

  const navigateToList = useCallback(() => {
    window.location.hash = ""
    // hashchange doesn't fire when setting to "", so update manually
    setView({ mode: "list" })
  }, [])

  const navigateToStyle = useCallback((name: string) => {
    window.location.hash = encodeURIComponent(name)
  }, [])

  const navigateToCreate = useCallback(() => {
    window.location.hash = CREATE_HASH
  }, [])

  return {
    view,
    previewHtml,
    previewLoading,
    refreshPreview,
    setStyles,
    isWorkspace: view.mode !== "list",
    styleName: view.mode === "preview" ? view.name : null,
    navigateToList,
    navigateToStyle,
    navigateToCreate,
  }
}
