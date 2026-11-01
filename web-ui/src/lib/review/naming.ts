// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Frame names for the comment tool: A, B, … Z, AA, AB, … ZZ, AAA (bijective base 26).
 * Names come from a per-deck sequence that only grows, so a deleted name is never reused.
 */

import { NAME_RE } from "@/lib/review/schema"

/** Name for sequence number `index` (0 → A, 25 → Z, 26 → AA, 701 → ZZ, 702 → AAA). */
export function frameName(index: number): string {
  let n = Math.max(0, Math.floor(index)) + 1
  let name = ""
  while (n > 0) {
    const m = (n - 1) % 26
    name = String.fromCharCode(65 + m) + name
    n = Math.floor((n - 1) / 26)
  }
  return name
}

/** Sequence number of `name` (inverse of `frameName`); -1 when it is not a frame name. */
export function nameIndex(name: string): number {
  if (!NAME_RE.test(name)) return -1
  let n = 0
  for (const ch of name) n = n * 26 + (ch.charCodeAt(0) - 64)
  return n - 1
}

/** The sequence value that comes after every name in `names` (0 when there are none). */
export function nextSeq(names: Iterable<string>): number {
  let seq = 0
  for (const name of names) seq = Math.max(seq, nameIndex(name) + 1)
  return seq
}
