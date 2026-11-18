// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Keyboard movement in a card gallery laid out as sections, one after another,
 * each section wrapped into rows of `cols` cards (the `/` picker and the choice chips).
 */

/** Widest the `/` gallery panel gets; it never exceeds the window minus its margins. */
export const SLASH_PANEL_MAX_WIDTH = 640
/** Space kept between the panel and the window edges. */
export const SLASH_PANEL_MARGIN = 12

/** Width of the `/` gallery panel in a window `viewportWidth` wide. */
export function slashPanelWidth(viewportWidth: number): number {
  return Math.max(0, Math.min(SLASH_PANEL_MAX_WIDTH, viewportWidth - SLASH_PANEL_MARGIN * 2))
}

/** Cards per row in the `/` gallery panel `panelWidth` wide (compact cards, about 140px or wider). */
export function galleryColumns(panelWidth: number): number {
  return panelWidth >= 560 ? 4 : panelWidth >= 400 ? 3 : 2
}

/** Sizes of the runs of consecutive items sharing a key (the sections of a flat, grouped list). */
export function runSizes<T>(items: T[], key: (item: T) => unknown): number[] {
  const sizes: number[] = []
  let previous: unknown = undefined
  items.forEach((item, i) => {
    const k = key(item)
    if (i > 0 && k === previous) sizes[sizes.length - 1] += 1
    else sizes.push(1)
    previous = k
  })
  return sizes
}

const ARROWS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"])

/**
 * The index an arrow key moves to, or null for any other key.
 *
 * Left/right step through the flat order. Up/down keep the column, crossing section
 * boundaries; a shorter row takes its last card. Edges stop rather than wrap.
 *
 * @param sizes - Card count of each section, in display order
 * @param index - Currently active card (flat index across sections)
 * @param key - `KeyboardEvent.key`
 * @param cols - Cards per row
 */
export function gridMove(sizes: number[], index: number, key: string, cols: number): number | null {
  if (!ARROWS.has(key)) return null
  const total = sizes.reduce((a, b) => a + b, 0)
  if (total === 0) return 0
  const current = Math.max(0, Math.min(total - 1, index))
  if (key === "ArrowLeft") return Math.max(0, current - 1)
  if (key === "ArrowRight") return Math.min(total - 1, current + 1)

  const rows: { start: number; length: number }[] = []
  let start = 0
  for (const size of sizes) {
    for (let offset = 0; offset < size; offset += cols) rows.push({ start: start + offset, length: Math.min(cols, size - offset) })
    start += size
  }
  const row = rows.findIndex((r) => current >= r.start && current < r.start + r.length)
  const col = current - rows[row].start
  const target = rows[key === "ArrowUp" ? row - 1 : row + 1]
  if (!target) return current
  return target.start + Math.min(col, target.length - 1)
}
