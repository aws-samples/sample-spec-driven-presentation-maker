// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useStyleWorkspace — Hash routing for the /styles page.
 *
 * Mirrors useWorkspace (decks) but much simpler: no polling, no deck state.
 * Hash values: "" (list), "#create" (new style), "#{name}" (preview).
 *
 * Preview HTML is resolved from the preloaded styles array (passed via
 * setStyles) to eliminate the /styles/{name} fetch round-trip. Falls back to
 * fetchStyleHtml only when the style is not in the preloaded set (e.g.
 * direct navigation via URL hash before the list has loaded).
 */

"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { fetchStyleHtml, type StyleEntry } from "@/services/deckService"

export type StyleView = { mode: "list" } | { mode: "preview"; name: string } | { mode: "create" }

function parseHash(hash: string): StyleView {
  const raw = hash.replace("#", "")
  if (!raw) return { mode: "list" }
  if (raw === "create") return { mode: "create" }
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

    // Try resolving from preloaded styles (instant, no round-trip)
    const cached = stylesRef.current.find(s => s.name === view.name)
    if (cached?.html) {
      setPreviewHtml(cached.html)
      setPreviewLoading(false)
      return
    }

    // Fallback: fetch from server (e.g. direct URL navigation before list loaded)
    let cancelled = false
    setPreviewLoading(true)
    fetchStyleHtml(view.name, idToken).then(html => {
      if (!cancelled) { setPreviewHtml(html); setPreviewLoading(false) }
    })
    return () => { cancelled = true }
  }, [view, idToken, previewVersion])

  const refreshPreview = useCallback(() => {
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
    window.location.hash = "create"
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
