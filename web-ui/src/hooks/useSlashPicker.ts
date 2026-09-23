// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useSlashPicker — State and keyboard handling for the chat input slash picker.
 */

"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { KeyboardEvent, RefObject } from "react"
import { buildToken, detectSlashFragment, filterItems, type PickerItem } from "@/lib/slashToken"

interface UseSlashPickerArgs {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  value: string
  setValue: (next: string) => void
  items: PickerItem[]
  onInserted?: () => void
}

interface UseSlashPickerResult {
  open: boolean
  query: string
  filtered: PickerItem[]
  activeIndex: number
  setActiveIndex: (index: number) => void
  onInputChange: (value: string, caret: number) => void
  onSelectionChange: () => void
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>, isComposing: boolean) => boolean
  select: (item: PickerItem) => void
  close: () => void
}

interface ActiveFragment {
  start: number
  query: string
  caret: number
}

export function useSlashPicker({
  textareaRef,
  value,
  setValue,
  items,
  onInserted,
}: UseSlashPickerArgs): UseSlashPickerResult {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [activeIndex, setActiveIndex] = useState(0)
  const fragmentRef = useRef<ActiveFragment | null>(null)
  const knownStartRef = useRef<number | null>(null)
  const dismissedStartRef = useRef<number | null>(null)
  const queryRef = useRef("")

  const filtered = useMemo(() => filterItems(items, query), [items, query])

  useEffect(() => {
    setActiveIndex((current) => {
      if (filtered.length === 0) return 0
      return Math.min(current, filtered.length - 1)
    })
  }, [filtered.length])

  const close = useCallback(() => {
    setOpen(false)
  }, [])

  const onInputChange = useCallback((nextValue: string, caret: number) => {
    const knownStart = knownStartRef.current
    if (knownStart !== null && nextValue[knownStart] !== "/") {
      knownStartRef.current = null
      dismissedStartRef.current = null
    }

    const fragment = detectSlashFragment(nextValue, caret)
    if (!fragment) {
      fragmentRef.current = null
      setOpen(false)
      return
    }

    fragmentRef.current = { ...fragment, caret }
    if (queryRef.current !== fragment.query) {
      queryRef.current = fragment.query
      setQuery(fragment.query)
      setActiveIndex(0)
    }

    if (fragment.start !== knownStartRef.current) {
      knownStartRef.current = fragment.start
      dismissedStartRef.current = null
      setOpen(true)
    } else if (dismissedStartRef.current !== fragment.start) {
      setOpen(true)
    }
  }, [])

  const onSelectionChange = useCallback(() => {
    const textarea = textareaRef.current
    if (!textarea) {
      setOpen(false)
      return
    }

    const caret = textarea.selectionStart
    const fragment = detectSlashFragment(value, caret)
    if (!fragment || fragment.start !== knownStartRef.current) {
      fragmentRef.current = null
      setOpen(false)
      return
    }

    fragmentRef.current = { ...fragment, caret }
  }, [textareaRef, value])

  const select = useCallback((item: PickerItem) => {
    const textarea = textareaRef.current
    const caret = textarea?.selectionStart ?? fragmentRef.current?.caret
    if (caret == null) return

    const fragment = detectSlashFragment(value, caret)
    if (!fragment) {
      setOpen(false)
      return
    }

    const token = buildToken(item)
    const nextValue = value.slice(0, fragment.start) + token + value.slice(caret)
    const nextCaret = fragment.start + token.length

    fragmentRef.current = null
    knownStartRef.current = null
    dismissedStartRef.current = null
    queryRef.current = ""
    setQuery("")
    setActiveIndex(0)
    setOpen(false)
    setValue(nextValue)
    onInserted?.()

    requestAnimationFrame(() => {
      textarea?.focus()
      textarea?.setSelectionRange(nextCaret, nextCaret)
    })
  }, [onInserted, setValue, textareaRef, value])

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>, isComposing: boolean): boolean => {
    if (isComposing || !open) return false

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault()
        if (filtered.length > 0) setActiveIndex((current) => (current + 1) % filtered.length)
        return true
      case "ArrowUp":
        event.preventDefault()
        if (filtered.length > 0) setActiveIndex((current) => (current - 1 + filtered.length) % filtered.length)
        return true
      case "Enter":
      case "Tab": {
        event.preventDefault()
        const item = filtered[activeIndex]
        if (item) select(item)
        return true
      }
      case "Escape":
        event.preventDefault()
        dismissedStartRef.current = fragmentRef.current?.start ?? knownStartRef.current
        close()
        return true
      default:
        return false
    }
  }, [activeIndex, close, filtered, open, select])

  return {
    open,
    query,
    filtered,
    activeIndex,
    setActiveIndex,
    onInputChange,
    onSelectionChange,
    onKeyDown,
    select,
    close,
  }
}
