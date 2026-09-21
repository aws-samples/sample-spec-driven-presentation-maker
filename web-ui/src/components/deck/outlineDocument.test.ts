// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, expect, it } from "vitest"
import {
  addedSlugs,
  duplicateSlug,
  getDeckName,
  getSubItemText,
  isPlaceholderSlug,
  newSlide,
  nextPlaceholderSlug,
  parseOutlineDocument,
  serializeOutline,
  setDeckName,
  setSlideMessage,
  setSubItemText,
  type SlideNode,
} from "./outlineDocument"
import { diffLines, diffStats, formatUnifiedDiff } from "./unifiedDiff"

const SAMPLE = `# Spec-Driven Presentation Maker

## オープニング

- [title] Spec-Driven Presentation Maker — 伝えたいことを先に設計する
  - body: タイトルスライド。
  - visual: title/subtitle/date。
  - evidence: 記事冒頭 https://example.com/

## 課題

- [problem] 資料作成の時間の多くは「見た目の作業」に費やされている
  - body: 一行目。
  - body: 二行目（body が二つある）。
  - visual: 左右対比。
  - evidence: 記事「節」

<!-- agent note: keep the order -->
- [ai-not-enough]   AIに「作って」と言うだけでは解決しない
    - visual: 失敗フロー。
Some stray prose that is not a slide.
- [TBD] placeholder
`

const slides = (md: string) => parseOutlineDocument(md).nodes.filter((n): n is SlideNode => n.type === "slide")

describe("outlineDocument round trip", () => {
  it("serializes an unchanged document byte for byte", () => {
    expect(serializeOutline(parseOutlineDocument(SAMPLE))).toBe(SAMPLE)
  })

  it("round-trips without a trailing newline and an empty file", () => {
    const noNl = SAMPLE.trimEnd()
    expect(serializeOutline(parseOutlineDocument(noNl))).toBe(noNl)
    expect(serializeOutline(parseOutlineDocument(""))).toBe("")
  })

  it("keeps odd spacing, comments and stray prose verbatim", () => {
    const doc = parseOutlineDocument(SAMPLE)
    const s = slides(SAMPLE)
    expect(s[2].raw).toBe("- [ai-not-enough]   AIに「作って」と言うだけでは解決しない")
    expect(s[2].indent).toBe("    ")
    expect(doc.nodes.some((n) => n.type === "prose" && n.text === "<!-- agent note: keep the order -->")).toBe(true)
    expect(getDeckName(doc)).toBe("Spec-Driven Presentation Maker")
  })

  it("re-emits only edited lines in canonical form", () => {
    const doc = parseOutlineDocument(SAMPLE)
    const idx = doc.nodes.findIndex((n) => n.type === "slide" && n.slug === "ai-not-enough")
    const edited = setSlideMessage(doc.nodes[idx] as SlideNode, "設計なき依頼は解決しない")
    const nodes = [...doc.nodes]
    nodes[idx] = edited
    const out = serializeOutline({ ...doc, nodes })
    expect(out).toContain("- [ai-not-enough] 設計なき依頼は解決しない\n    - visual: 失敗フロー。")
    // Everything else identical
    expect(out.replace("- [ai-not-enough] 設計なき依頼は解決しない", s0(2))).toBe(SAMPLE)
    function s0(i: number) {
      return slides(SAMPLE)[i].raw!
    }
  })

  it("edits repeated sub-items as multi-line text and back", () => {
    const problem = slides(SAMPLE)[1]
    expect(getSubItemText(problem, "body")).toBe("一行目。\n二行目（body が二つある）。")
    const next = setSubItemText(problem, "body", "一行目。\n\n三行目に差し替え。")
    expect(next.subItems.map((s) => `${s.key}:${s.value}`)).toEqual([
      "body:一行目。",
      "body:三行目に差し替え。",
      "visual:左右対比。",
      "evidence:記事「節」",
    ])
    // visual / evidence keep their raw lines
    expect(next.subItems[2].raw).toBeDefined()
    expect(next.subItems[0].raw).toBeUndefined()
  })

  it("inserts a new key in canonical order and drops emptied keys", () => {
    const ai = slides(SAMPLE)[2] // has only visual
    const withBody = setSubItemText(ai, "body", "本文")
    expect(withBody.subItems.map((s) => s.key)).toEqual(["body", "visual"])
    const withEvidence = setSubItemText(withBody, "evidence", "出典")
    expect(withEvidence.subItems.map((s) => s.key)).toEqual(["body", "visual", "evidence"])
    const cleared = setSubItemText(withEvidence, "visual", "")
    expect(cleared.subItems.map((s) => s.key)).toEqual(["body", "evidence"])
    expect(serializeOutline({ nodes: [cleared], trailingNewline: false })).toBe(
      "- [ai-not-enough]   AIに「作って」と言うだけでは解決しない\n    - body: 本文\n    - evidence: 出典",
    )
  })

  it("returns the same node when nothing changed", () => {
    const n = slides(SAMPLE)[0]
    expect(setSlideMessage(n, n.message)).toBe(n)
    expect(setSubItemText(n, "body", getSubItemText(n, "body"))).toBe(n)
  })

  it("creates placeholder and duplicate slugs that are unique", () => {
    const doc = parseOutlineDocument(SAMPLE)
    expect(nextPlaceholderSlug(doc)).toBe("slide-5")
    expect(isPlaceholderSlug("slide-5")).toBe(true)
    expect(isPlaceholderSlug("title")).toBe(false)
    expect(duplicateSlug(doc, "title")).toBe("title-copy")
    const withCopy = { ...doc, nodes: [...doc.nodes, newSlide("title-copy")] }
    expect(duplicateSlug(withCopy, "title")).toBe("title-copy-2")
    expect(addedSlugs(doc, withCopy)).toEqual(["title-copy"])
  })

  it("renames or inserts the deck name heading", () => {
    const doc = parseOutlineDocument(SAMPLE)
    expect(serializeOutline(setDeckName(doc, "New name"))).toMatch(/^# New name\n/)
    const headless = parseOutlineDocument("## A\n- [x] y\n")
    expect(serializeOutline(setDeckName(headless, "Deck"))).toBe("# Deck\n\n## A\n- [x] y\n")
    expect(setDeckName(doc, "Spec-Driven Presentation Maker")).toBe(doc)
  })
})

describe("unifiedDiff", () => {
  const before = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n"
  const after = "a\nb\nC\nd\ne\nf\ng\nh\ni\nj\nk\n"

  it("reconstructs both sides from the ops", () => {
    const ops = diffLines(before, after)
    expect(ops.filter((o) => o.kind !== "add").map((o) => o.text).join("\n") + "\n").toBe(before)
    expect(ops.filter((o) => o.kind !== "del").map((o) => o.text).join("\n") + "\n").toBe(after)
    expect(diffStats(ops)).toEqual({ added: 2, deleted: 1 })
  })

  it("formats hunks with three lines of context", () => {
    expect(formatUnifiedDiff(diffLines(before, after))).toBe(
      ["@@ -1,6 +1,6 @@", " a", " b", "-c", "+C", " d", " e", " f", "@@ -8,3 +8,4 @@", " h", " i", " j", "+k"].join("\n"),
    )
  })

  it("returns an empty string when nothing changed", () => {
    expect(formatUnifiedDiff(diffLines(before, before))).toBe("")
  })

  it("merges nearby changes into one hunk", () => {
    const ops = diffLines("a\nb\nc\nd\ne\n", "a\nB\nc\nD\ne\n")
    expect(formatUnifiedDiff(ops)).toBe(["@@ -1,5 +1,5 @@", " a", "-b", "+B", " c", "-d", "+D", " e"].join("\n"))
  })
})
