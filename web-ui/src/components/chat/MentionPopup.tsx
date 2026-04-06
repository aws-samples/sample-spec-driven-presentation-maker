// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * MentionPopup — Autocomplete popup for @mentions in chat input.
 * Shows current deck slides and other decks with keyboard navigation.
 * The selected item's PNG preview is shown large on the right side.
 */

"use client"

import { useState, useEffect, useCallback, KeyboardEvent } from "react"
import { createPortal } from "react-dom"
import { Layers, FileText } from "lucide-react"
import { useIsMobile } from "@/hooks/UseMobile"

export interface MentionItem {
  /** Display label (e.g. "Page 1", "営業提案テンプレート"). */
  label: string
  /** Text to insert into the textarea. */
  insertText: string
  /** "slide" for current deck slides, "deck" for other decks. */
  type: "slide" | "deck"
  /** Deck ID for deck mentions. */
  deckId?: string
  /** Page number for slide mentions. */
  page?: number
  /** Preview image URL (slide PNG or deck thumbnail). */
  previewUrl?: string | null
}

interface MentionPopupProps {
  /** Whether the popup is visible. */
  visible: boolean
  /** Current search query (text after @). */
  query: string
  /** Available mention items. */
  items: MentionItem[]
  /** Called when user selects an item. */
  onSelect: (item: MentionItem) => void
  /** Called when popup should close. */
  onClose: () => void
  /** Position relative to textarea. */
  position: { top: number; left: number }
  /** Ref to textarea for portal positioning. */
  textareaRef?: React.RefObject<HTMLTextAreaElement | null>
}

/**
 * Renders a floating autocomplete popup with a large preview panel.
 *
 * @param props - MentionPopupProps
 */
export function MentionPopup({ visible, query, items, onSelect, onClose, position, textareaRef }: MentionPopupProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const isMobile = useIsMobile()

  const filtered = items.filter((item) =>
    item.label.toLowerCase().includes(query.toLowerCase()),
  ).slice(0, 8)

  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent): boolean => {
      if (!visible || filtered.length === 0) return false

      if (e.key === "ArrowDown") {
        e.preventDefault()
        setSelectedIndex((prev) => (prev + 1) % filtered.length)
        return true
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setSelectedIndex((prev) => (prev - 1 + filtered.length) % filtered.length)
        return true
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault()
        onSelect(filtered[selectedIndex])
        return true
      }
      if (e.key === "Escape") {
        e.preventDefault()
        onClose()
        return true
      }
      return false
    },
    [visible, filtered, selectedIndex, onSelect, onClose],
  )

  ;(MentionPopup as unknown as { _handleKeyDown: typeof handleKeyDown })._handleKeyDown = handleKeyDown

  if (!visible || filtered.length === 0) return null

  const slides = filtered.filter((i) => i.type === "slide")
  const decks = filtered.filter((i) => i.type === "deck")
  const selectedItem = filtered[selectedIndex]

  let globalIndex = 0

  // Compute fixed position from textarea ref
  const taRect = textareaRef?.current?.getBoundingClientRect()
  const popupStyle = taRect
    ? { position: "fixed" as const, bottom: window.innerHeight - taRect.top + 8, right: window.innerWidth - taRect.right }
    : { position: "absolute" as const, bottom: position.top, right: 0 }

  return createPortal(
    <div
      className="z-[9999] flex gap-2"
      style={popupStyle}
    >
      {/* Large preview panel — desktop only, positioned left of list */}
      {!isMobile && selectedItem?.previewUrl && (
        <div className="bg-popover border border-border rounded-lg shadow-lg overflow-hidden w-[280px] order-first">
          <img
            src={selectedItem.previewUrl}
            alt={selectedItem.label}
            className="w-full"
          />
          <div className="px-3 py-1.5 text-xs text-muted-foreground border-t border-border/40">
            {selectedItem.label}
          </div>
        </div>
      )}

      {/* List panel */}
      <div
        className="bg-popover border border-border rounded-lg shadow-lg py-1 max-h-[300px] overflow-y-auto min-w-[200px] max-w-[min(240px,calc(100vw-2rem))]"
        role="listbox"
        aria-label="Mention suggestions"
      >
        {slides.length > 0 && (
          <>
            <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              Current Deck
            </div>
            {slides.map((item) => {
              const idx = globalIndex++
              return (
                <button
                  key={`slide-${item.page}`}
                  type="button"
                  role="option"
                  aria-selected={idx === selectedIndex}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left transition-colors ${
                    idx === selectedIndex ? "bg-muted" : "hover:bg-muted/50"
                  }`}
                  onClick={() => onSelect(item)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                >
                  <Layers className="h-3.5 w-3.5 text-muted-foreground flex-none" />
                  <span className="truncate">{item.label}</span>
                </button>
              )
            })}
          </>
        )}

        {decks.length > 0 && (
          <>
            <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              Other Decks
            </div>
            {decks.map((item) => {
              const idx = globalIndex++
              return (
                <button
                  key={`deck-${item.deckId}`}
                  type="button"
                  role="option"
                  aria-selected={idx === selectedIndex}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left transition-colors ${
                    idx === selectedIndex ? "bg-muted" : "hover:bg-muted/50"
                  }`}
                  onClick={() => onSelect(item)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                >
                  <FileText className="h-3.5 w-3.5 text-muted-foreground flex-none" />
                  <span className="truncate">{item.label}</span>
                </button>
              )
            })}
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}
