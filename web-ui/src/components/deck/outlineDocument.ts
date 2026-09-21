// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * outlineDocument — Editable, lossless model of `specs/outline.md`.
 *
 * `outlineParser.ts` is the read-only view model used by the storyboard. This module is
 * the *editing* model: every line of the file is represented, so that
 * `serializeOutline(parseOutlineDocument(md)) === md` holds byte for byte, and lines the
 * user never touched are written back exactly as the agent wrote them.
 *
 * Format (fixed — see sdpm/references/workflows/orchestrator.md):
 *   # Deck name                 (optional, first heading)
 *   ## Chapter                  → SectionNode
 *   - [slug] claim              → SlideNode
 *     - body: …                 → SlideNode.subItems (body | visual | evidence, repeatable)
 *     - visual: …
 *     - evidence: …
 *   anything else, blank lines  → ProseNode (preserved verbatim)
 *
 * Every node carries a UI-stable `id` (never serialized) for React keys, drag & drop and
 * layout animations. Unchanged nodes keep their `raw` line(s); edited nodes drop `raw` and
 * are re-emitted in canonical form.
 */

import type { SubItemKey } from "./outlineParser"

export const SUB_ITEM_KEYS: readonly SubItemKey[] = ["body", "visual", "evidence"] as const

export interface SubItemNode {
  key: SubItemKey
  value: string
  /** Original line, kept while the value is unchanged. */
  raw?: string
}

export interface SlideNode {
  id: string
  type: "slide"
  slug: string
  message: string
  subItems: SubItemNode[]
  /** Original `- [slug] message` line, kept while slug/message are unchanged. */
  raw?: string
  /** Indent used for sub-items in the source (default two spaces). */
  indent: string
}

export interface SectionNode {
  id: string
  type: "section"
  title: string
  raw?: string
}

export interface ProseNode {
  id: string
  type: "prose"
  /** Verbatim line (may be empty for a blank line). */
  text: string
}

export type OutlineNode = SlideNode | SectionNode | ProseNode

export interface OutlineDocument {
  nodes: OutlineNode[]
  /** True when the source ended with a newline (preserved on serialize). */
  trailingNewline: boolean
}

const SLIDE_RE = /^-\s*\[([^\]]+)\]\s*(.*)$/
const SUB_ITEM_RE = /^(\s+)-\s*(body|visual|evidence):\s*(.*)$/
const SECTION_RE = /^##\s+(.+?)\s*$/
const PLACEHOLDER_SLUG_RE = /^slide-\d+$/

let counter = 0
/** Generate a UI-stable node id. Not serialized. */
export function newNodeId(): string {
  counter += 1
  return `n${Date.now().toString(36)}${counter.toString(36)}`
}

// ---------------------------------------------------------------------------
// Parse
// ---------------------------------------------------------------------------

export function parseOutlineDocument(markdown: string): OutlineDocument {
  const trailingNewline = markdown.endsWith("\n")
  const body = trailingNewline ? markdown.slice(0, -1) : markdown
  const lines = body === "" ? [] : body.split("\n")
  const nodes: OutlineNode[] = []
  let current: SlideNode | null = null

  for (const line of lines) {
    const slide = line.match(SLIDE_RE)
    if (slide) {
      current = {
        id: newNodeId(),
        type: "slide",
        slug: slide[1],
        message: slide[2].trim(),
        subItems: [],
        raw: line,
        indent: "  ",
      }
      nodes.push(current)
      continue
    }
    const sub = current ? line.match(SUB_ITEM_RE) : null
    if (sub && current) {
      if (current.subItems.length === 0) current.indent = sub[1]
      current.subItems.push({ key: sub[2] as SubItemKey, value: sub[3].trim(), raw: line })
      continue
    }
    const section = line.match(SECTION_RE)
    if (section) {
      current = null
      nodes.push({ id: newNodeId(), type: "section", title: section[1], raw: line })
      continue
    }
    // Anything else (including a blank line) ends the sub-item context, so that line order
    // is preserved exactly on serialize.
    current = null
    nodes.push({ id: newNodeId(), type: "prose", text: line })
  }

  return { nodes, trailingNewline }
}

// ---------------------------------------------------------------------------
// Serialize
// ---------------------------------------------------------------------------

export function serializeSlide(node: SlideNode): string[] {
  const out: string[] = [node.raw ?? `- [${node.slug}] ${node.message}`.trimEnd()]
  for (const item of node.subItems) {
    if (item.raw !== undefined) out.push(item.raw)
    else if (item.value.trim() !== "") out.push(`${node.indent}- ${item.key}: ${item.value}`)
  }
  return out
}

export function serializeOutline(doc: OutlineDocument): string {
  const lines: string[] = []
  for (const node of doc.nodes) {
    if (node.type === "slide") lines.push(...serializeSlide(node))
    else if (node.type === "section") lines.push(node.raw ?? `## ${node.title}`)
    else lines.push(node.text)
  }
  return lines.join("\n") + (doc.trailingNewline ? "\n" : "")
}

// ---------------------------------------------------------------------------
// Editing helpers (pure; return new nodes, never mutate)
// ---------------------------------------------------------------------------

/** Read a field as the user edits it: repeated sub-items of one key become lines. */
export function getSubItemText(node: SlideNode, key: SubItemKey): string {
  return node.subItems.filter((s) => s.key === key).map((s) => s.value).join("\n")
}

/**
 * Write a field back. Each non-empty line becomes one `- key:` sub-item, placed where the
 * first existing item of that key was (or in canonical key order when the key is new).
 * Untouched items of other keys keep their `raw`.
 */
export function setSubItemText(node: SlideNode, key: SubItemKey, text: string): SlideNode {
  if (getSubItemText(node, key) === text) return node
  const values = text.split("\n").map((v) => v.trim()).filter((v) => v !== "")
  const fresh: SubItemNode[] = values.map((value) => ({ key, value }))
  const existingIdx = node.subItems.findIndex((s) => s.key === key)
  const others = node.subItems.filter((s) => s.key !== key)
  let insertAt: number
  if (existingIdx >= 0) {
    insertAt = node.subItems.slice(0, existingIdx).filter((s) => s.key !== key).length
  } else {
    const rank = SUB_ITEM_KEYS.indexOf(key)
    insertAt = others.findIndex((s) => SUB_ITEM_KEYS.indexOf(s.key) > rank)
    if (insertAt < 0) insertAt = others.length
  }
  const subItems = [...others.slice(0, insertAt), ...fresh, ...others.slice(insertAt)]
  return { ...node, subItems }
}

export function setSlideMessage(node: SlideNode, message: string): SlideNode {
  const next = message.replace(/\s*\n\s*/g, " ").trim()
  if (next === node.message) return node
  return { ...node, message: next, raw: undefined }
}

export function setSectionTitle(node: SectionNode, title: string): SectionNode {
  const next = title.replace(/\s*\n\s*/g, " ").trim()
  if (next === node.title) return node
  return { ...node, title: next, raw: undefined }
}

/** Placeholder slug for a new slide: `slide-N`, unique within the document. */
export function nextPlaceholderSlug(doc: OutlineDocument): string {
  const used = new Set(doc.nodes.filter((n): n is SlideNode => n.type === "slide").map((n) => n.slug))
  let n = used.size + 1
  while (used.has(`slide-${n}`)) n += 1
  return `slide-${n}`
}

/** Duplicate slug: `<slug>-copy`, then `-copy-2`, … */
export function duplicateSlug(doc: OutlineDocument, slug: string): string {
  const used = new Set(doc.nodes.filter((n): n is SlideNode => n.type === "slide").map((n) => n.slug))
  const base = `${slug}-copy`
  if (!used.has(base)) return base
  let i = 2
  while (used.has(`${base}-${i}`)) i += 1
  return `${base}-${i}`
}

export function newSlide(slug: string): SlideNode {
  return { id: newNodeId(), type: "slide", slug, message: "", subItems: [], indent: "  " }
}

export function newSection(title = ""): SectionNode {
  return { id: newNodeId(), type: "section", title }
}

export function blankLine(): ProseNode {
  return { id: newNodeId(), type: "prose", text: "" }
}

export function isPlaceholderSlug(slug: string): boolean {
  return PLACEHOLDER_SLUG_RE.test(slug)
}

/** Slugs of slides present in `next` but absent from `base` (for the send message). */
export function addedSlugs(base: OutlineDocument, next: OutlineDocument): string[] {
  const before = new Set(base.nodes.filter((n): n is SlideNode => n.type === "slide").map((n) => n.slug))
  return next.nodes
    .filter((n): n is SlideNode => n.type === "slide" && !before.has(n.slug))
    .map((n) => n.slug)
}

/** Deck name from the first `# ` heading, if any. */
export function getDeckName(doc: OutlineDocument): string | null {
  for (const n of doc.nodes) {
    if (n.type === "prose") {
      const m = n.text.match(/^#\s+(.+?)\s*$/)
      if (m) return m[1]
      if (n.text.trim() !== "") return null
    } else return null
  }
  return null
}

export function setDeckName(doc: OutlineDocument, name: string): OutlineDocument {
  const next = name.replace(/\s*\n\s*/g, " ").trim()
  const nodes = [...doc.nodes]
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]
    if (n.type !== "prose") break
    if (/^#\s+/.test(n.text)) {
      if (n.text.replace(/^#\s+/, "").trim() === next) return doc
      nodes[i] = { ...n, text: `# ${next}` }
      return { ...doc, nodes }
    }
    if (n.text.trim() !== "") break
  }
  if (next === "") return doc
  return { ...doc, nodes: [{ id: newNodeId(), type: "prose", text: `# ${next}` }, blankLine(), ...nodes] }
}
