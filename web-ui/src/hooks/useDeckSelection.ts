// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useDeckSelection — Multi-select state for the deck list (bulk actions).
 *
 * Selection mode is entered explicitly (the "Select" button) or implicitly by
 * toggling a card. Shift-click extends from the last toggled card over the
 * visible order. Escape exits, ⌘/Ctrl+A selects every visible deck — both only
 * while selection mode is active and focus is not inside a text field.
 *
 * @param orderedIds - Visible deck IDs in display order (range selection + select all)
 * @param enabled - Whether selection is allowed at all (owner tab, not searching);
 *                  turning this off exits selection mode
 */

"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"

function isTextInput(el: Element | null): boolean {
  if (!el) return false
  const tag = el.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement).isContentEditable
}

export function useDeckSelection(orderedIds: string[], enabled: boolean) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [explicitMode, setExplicitMode] = useState(false)
  const lastClickedRef = useRef<string | null>(null)

  const selectionMode = enabled && (explicitMode || selectedIds.size > 0)

  const exit = useCallback(() => {
    setExplicitMode(false)
    setSelectedIds(new Set())
    lastClickedRef.current = null
  }, [])

  const enter = useCallback(() => setExplicitMode(true), [])

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(orderedIds))
  }, [orderedIds])

  const toggle = useCallback((id: string, shiftKey: boolean) => {
    // Read the anchor now: the state updater below runs lazily, after the ref is advanced.
    const anchor = lastClickedRef.current
    lastClickedRef.current = id
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (shiftKey && anchor && anchor !== id) {
        const a = orderedIds.indexOf(anchor)
        const b = orderedIds.indexOf(id)
        if (a !== -1 && b !== -1) {
          const [from, to] = a < b ? [a, b] : [b, a]
          for (let i = from; i <= to; i++) next.add(orderedIds[i])
          return next
        }
      }
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }, [orderedIds])

  // Leave selection mode when the surface no longer allows it (tab switch, search, navigation).
  useEffect(() => {
    if (!enabled) exit()
  }, [enabled, exit])

  // Drop IDs that disappeared from the list (deleted elsewhere / list refreshed).
  const visible = useMemo(() => new Set(orderedIds), [orderedIds])
  useEffect(() => {
    setSelectedIds((prev) => {
      let changed = false
      const next = new Set<string>()
      for (const id of prev) {
        if (visible.has(id)) next.add(id); else changed = true
      }
      return changed ? next : prev
    })
  }, [visible])

  // Keyboard: Escape exits, ⌘/Ctrl+A selects all — only in selection mode.
  useEffect(() => {
    if (!selectionMode) return
    function onKeyDown(e: KeyboardEvent) {
      if (isTextInput(document.activeElement)) return
      if (e.key === "Escape") {
        e.preventDefault()
        exit()
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
        e.preventDefault()
        selectAll()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [selectionMode, exit, selectAll])

  return { selectionMode, selectedIds, enter, exit, toggle, selectAll }
}
