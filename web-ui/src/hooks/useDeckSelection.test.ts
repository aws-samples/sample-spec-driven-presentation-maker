// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { useDeckSelection } from "./useDeckSelection"

const ids = ["a", "b", "c", "d", "e"]

describe("useDeckSelection", () => {
  it("starts outside selection mode and enters on first toggle", () => {
    const { result } = renderHook(() => useDeckSelection(ids, true))
    expect(result.current.selectionMode).toBe(false)
    act(() => result.current.toggle("b", false))
    expect(result.current.selectionMode).toBe(true)
    expect([...result.current.selectedIds]).toEqual(["b"])
  })

  it("enter() shows selection mode with nothing selected; exit() clears", () => {
    const { result } = renderHook(() => useDeckSelection(ids, true))
    act(() => result.current.enter())
    expect(result.current.selectionMode).toBe(true)
    expect(result.current.selectedIds.size).toBe(0)
    act(() => result.current.toggle("a", false))
    act(() => result.current.exit())
    expect(result.current.selectionMode).toBe(false)
    expect(result.current.selectedIds.size).toBe(0)
  })

  it("shift-toggle extends a range from the last toggled card in either direction", () => {
    const { result } = renderHook(() => useDeckSelection(ids, true))
    act(() => result.current.toggle("d", false))
    act(() => result.current.toggle("b", true))
    expect([...result.current.selectedIds].sort()).toEqual(["b", "c", "d"])
    act(() => result.current.toggle("e", true))
    expect([...result.current.selectedIds].sort()).toEqual(["b", "c", "d", "e"])
  })

  it("selectAll selects every visible id", () => {
    const { result } = renderHook(() => useDeckSelection(ids, true))
    act(() => result.current.selectAll())
    expect(result.current.selectedIds.size).toBe(5)
  })

  it("drops ids that leave the visible list and exits when disabled", () => {
    const { result, rerender } = renderHook(
      ({ list, enabled }: { list: string[]; enabled: boolean }) => useDeckSelection(list, enabled),
      { initialProps: { list: ids, enabled: true } },
    )
    act(() => result.current.selectAll())
    rerender({ list: ["a", "c"], enabled: true })
    expect([...result.current.selectedIds].sort()).toEqual(["a", "c"])
    rerender({ list: ["a", "c"], enabled: false })
    expect(result.current.selectionMode).toBe(false)
    expect(result.current.selectedIds.size).toBe(0)
  })

  it("Escape exits and ⌘A selects all while in selection mode", () => {
    const { result } = renderHook(() => useDeckSelection(ids, true))
    act(() => result.current.toggle("a", false))
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "a", metaKey: true })) })
    expect(result.current.selectedIds.size).toBe(5)
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })) })
    expect(result.current.selectionMode).toBe(false)
  })

  it("ignores shortcuts outside selection mode", () => {
    const { result } = renderHook(() => useDeckSelection(ids, true))
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "a", metaKey: true })) })
    expect(result.current.selectedIds.size).toBe(0)
  })
})
