// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * unifiedDiff — Minimal line-level diff (LCS) with unified output.
 *
 * Used to tell the agent what the user changed in outline.md and to highlight changed lines
 * in the markdown drawer. Inputs are small (an outline is a few hundred lines at most), so a
 * plain O(n·m) LCS table is fine and keeps the implementation dependency-free.
 */

export type DiffOp = { kind: "equal" | "add" | "del"; text: string }

export function diffLines(before: string, after: string): DiffOp[] {
  const a = splitLines(before)
  const b = splitLines(after)
  const n = a.length
  const m = b.length
  // lcs[i][j] = length of LCS of a[i:] and b[j:]
  const lcs: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const ops: DiffOp[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ kind: "equal", text: a[i] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      ops.push({ kind: "del", text: a[i] })
      i++
    } else {
      ops.push({ kind: "add", text: b[j] })
      j++
    }
  }
  while (i < n) ops.push({ kind: "del", text: a[i++] })
  while (j < m) ops.push({ kind: "add", text: b[j++] })
  return ops
}

export interface DiffStats {
  added: number
  deleted: number
}

export function diffStats(ops: DiffOp[]): DiffStats {
  let added = 0
  let deleted = 0
  for (const op of ops) {
    if (op.kind === "add") added++
    else if (op.kind === "del") deleted++
  }
  return { added, deleted }
}

/**
 * Render ops as a unified diff body (hunks with `@@` headers, `context` equal lines around
 * each change). Returns "" when there are no changes.
 */
export function formatUnifiedDiff(ops: DiffOp[], context = 3): string {
  const out: string[] = []
  let oldLine = 1
  let newLine = 1
  let idx = 0
  while (idx < ops.length) {
    // Skip to the next change
    while (idx < ops.length && ops[idx].kind === "equal") {
      idx++
      oldLine++
      newLine++
    }
    if (idx >= ops.length) break
    // Hunk starts `context` lines before the change
    const start = Math.max(0, idx - context)
    let hunkOld = oldLine - (idx - start)
    let hunkNew = newLine - (idx - start)
    const lines: string[] = []
    let oldCount = 0
    let newCount = 0
    let k = start
    let trailingEqual = 0
    // Extend the hunk while changes are within 2*context of each other
    while (k < ops.length) {
      const op = ops[k]
      if (op.kind === "equal") {
        trailingEqual++
        if (trailingEqual > context) {
          // Look ahead: is another change within `context` lines? If so, keep going.
          let look = k
          let gap = 0
          while (look < ops.length && ops[look].kind === "equal" && gap < context) {
            look++
            gap++
          }
          if (look >= ops.length || ops[look].kind === "equal") break
        }
        lines.push(" " + op.text)
        oldCount++
        newCount++
      } else {
        trailingEqual = 0
        if (op.kind === "del") {
          lines.push("-" + op.text)
          oldCount++
        } else {
          lines.push("+" + op.text)
          newCount++
        }
      }
      k++
    }
    // Trim trailing context beyond `context`
    let trim = 0
    for (let t = lines.length - 1; t >= 0 && lines[t].startsWith(" "); t--) trim++
    if (trim > context) {
      const extra = trim - context
      lines.splice(lines.length - extra, extra)
      oldCount -= extra
      newCount -= extra
      k -= extra
    }
    hunkOld = Math.max(hunkOld, 1)
    hunkNew = Math.max(hunkNew, 1)
    out.push(`@@ -${hunkOld},${oldCount} +${hunkNew},${newCount} @@`)
    out.push(...lines)
    // Advance counters to k
    for (let t = idx; t < k; t++) {
      if (ops[t].kind !== "add") oldLine++
      if (ops[t].kind !== "del") newLine++
    }
    idx = k
  }
  return out.join("\n")
}

function splitLines(text: string): string[] {
  if (text === "") return []
  const lines = text.split("\n")
  if (lines[lines.length - 1] === "") lines.pop()
  return lines
}
