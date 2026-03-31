// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useCompositionSafe — Hook to safely detect IME composition state.
 *
 * Safari fires compositionend BEFORE keydown (violating W3C spec),
 * so e.isComposing is already false when keydown fires.
 * This hook uses setTimeout(0) to keep the composing flag true
 * through the current event loop, fixing the Safari bug.
 *
 * @returns onCompositionStart, onCompositionEnd — attach to textarea
 * @returns getIsComposing — call inside keydown handler with the event
 *
 * @see https://bugs.webkit.org/show_bug.cgi?id=165004
 */

import { useRef, useCallback } from "react"
import type { KeyboardEvent } from "react"

export function useCompositionSafe() {
  const isComposingRef = useRef(false)

  const onCompositionStart = useCallback(() => {
    isComposingRef.current = true
  }, [])

  const onCompositionEnd = useCallback(() => {
    // Delay reset to next event loop so keydown still sees composing=true
    setTimeout(() => {
      isComposingRef.current = false
    }, 0)
  }, [])

  /**
   * Check if IME composition is active. Combines native isComposing
   * with our Safari-safe ref.
   *
   * @param e - React KeyboardEvent from onKeyDown
   * @returns true if user is in the middle of IME composition
   */
  const getIsComposing = useCallback(
    (e: KeyboardEvent<HTMLElement>): boolean =>
      e.nativeEvent.isComposing || isComposingRef.current,
    [],
  )

  return { onCompositionStart, onCompositionEnd, getIsComposing }
}
