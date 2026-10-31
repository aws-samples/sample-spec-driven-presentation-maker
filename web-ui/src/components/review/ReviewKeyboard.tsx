// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewKeyboard — the comment tool's shortcuts while the slides surface is on screen
 * (SlideCarousel mounts it only then) and focus is not in a text field:
 * C toggles the tool; Esc closes an open card, else deselects, else turns the tool off (R1.4);
 * Delete / Backspace deletes the selected draft; ⌘Z / Ctrl+Z undoes the last delete.
 * The comment editor handles its own Enter / Esc.
 *
 * Also: with the tool off, a press on a slide outside any frame clears the selection
 * (the layer lets the pointer through then, so it cannot see the press itself).
 */

"use client"

import { useEffect, useRef } from "react"
import { useReview } from "@/components/review/ReviewProvider"
import { isTypingTarget } from "@/lib/review/interaction"

export function ReviewKeyboard() {
  const review = useReview()
  const ref = useRef(review)
  useEffect(() => { ref.current = review })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const r = ref.current
      if (!r?.enabled || e.defaultPrevented) return
      const typing = isTypingTarget(document.activeElement) || (e.target instanceof Element && isTypingTarget(e.target))
      if (typing) return
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "z") {
        if (r.canUndo) { e.preventDefault(); r.undoDelete() }
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === "c" || e.key === "C") {
        if (e.shiftKey) return
        e.preventDefault()
        r.toggleTool()
        return
      }
      if (e.key === "Escape") {
        if (r.editor) r.closeEditor(false)
        else if (r.selected) r.select(null)
        else if (r.toolOn) r.setToolOn(false)
        return
      }
      if ((e.key === "Delete" || e.key === "Backspace") && r.selected && r.drafts.some(d => d.name === r.selected)) {
        e.preventDefault()
        r.deleteFrame(r.selected)
      }
    }
    const onDown = (e: PointerEvent) => {
      const r = ref.current
      if (!r?.enabled || r.toolOn || !r.selected) return
      const el = e.target instanceof Element ? e.target : null
      if (el?.closest("[data-review-slide]") && !el.closest("[data-review-frame]")) r.select(null)
    }
    window.addEventListener("keydown", onKey)
    document.addEventListener("pointerdown", onDown, true)
    return () => {
      window.removeEventListener("keydown", onKey)
      document.removeEventListener("pointerdown", onDown, true)
    }
  }, [])

  return null
}
