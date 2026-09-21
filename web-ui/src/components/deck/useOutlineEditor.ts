// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { arrayMove } from "@dnd-kit/helpers"
import {
  blankLine,
  duplicateSlug,
  newSection,
  newSlide,
  nextPlaceholderSlug,
  parseOutlineDocument,
  serializeOutline,
  setDeckName,
  setSectionTitle,
  setSlideMessage,
  setSubItemText,
  type OutlineDocument,
  type OutlineNode,
  type ProseNode,
  type SectionNode,
  type SlideNode,
} from "./outlineDocument"
import type { SubItemKey } from "./outlineParser"
import { diffLines, diffStats } from "./unifiedDiff"

interface EditorState {
  doc: OutlineDocument
  base: string
  latestSeen: string
  past: OutlineDocument[]
  future: OutlineDocument[]
}

export type SlideDropTarget =
  | { kind: "slide"; id: string }
  | { kind: "chapter-end"; sectionId: string }

function sameDocument(a: OutlineDocument, b: OutlineDocument): boolean {
  return serializeOutline(a) === serializeOutline(b)
}

/** Keep motion/DnD keys stable when polling replaces a clean document. */
function reconcileIds(previous: OutlineDocument, next: OutlineDocument): OutlineDocument {
  const slideIds = new Map(
    previous.nodes.filter((node): node is SlideNode => node.type === "slide").map((node) => [node.slug, node.id]),
  )
  const sections = previous.nodes.filter((node): node is SectionNode => node.type === "section")
  let sectionIndex = 0
  const proseBuckets = new Map<string, string[]>()
  for (const node of previous.nodes) {
    if (node.type !== "prose") continue
    const bucket = proseBuckets.get(node.text) ?? []
    bucket.push(node.id)
    proseBuckets.set(node.text, bucket)
  }

  return {
    ...next,
    nodes: next.nodes.map((node) => {
      if (node.type === "slide") return { ...node, id: slideIds.get(node.slug) ?? node.id }
      if (node.type === "section") {
        const prior = sections[sectionIndex++]
        return { ...node, id: prior?.id ?? node.id }
      }
      const bucket = proseBuckets.get(node.text)
      return { ...node, id: bucket?.shift() ?? node.id }
    }),
  }
}

function isBlankLine(node: OutlineNode | undefined): node is ProseNode {
  return node?.type === "prose" && node.text === ""
}

function replaceNode(doc: OutlineDocument, id: string, update: (node: OutlineNode) => OutlineNode): OutlineDocument {
  const index = doc.nodes.findIndex((node) => node.id === id)
  if (index < 0) return doc
  const nextNode = update(doc.nodes[index])
  if (nextNode === doc.nodes[index]) return doc
  const nodes = [...doc.nodes]
  nodes[index] = nextNode
  return { ...doc, nodes }
}

function insertAtChapterEnd(doc: OutlineDocument, sectionId: string, node: SlideNode): OutlineDocument {
  const nodes = [...doc.nodes]
  let start = 0
  if (sectionId !== "root") {
    const sectionIndex = nodes.findIndex((entry) => entry.id === sectionId && entry.type === "section")
    if (sectionIndex < 0) return doc
    start = sectionIndex + 1
  }
  let end = start
  while (end < nodes.length && nodes[end].type !== "section") end++
  while (end > start && isBlankLine(nodes[end - 1])) end--
  nodes.splice(end, 0, node, blankLine())
  return { ...doc, nodes }
}

function moveSlideInDocument(doc: OutlineDocument, sourceId: string, target: SlideDropTarget): OutlineDocument {
  const sourceIndex = doc.nodes.findIndex((node) => node.id === sourceId && node.type === "slide")
  if (sourceIndex < 0) return doc
  const nodes = [...doc.nodes]
  const [source] = nodes.splice(sourceIndex, 1)

  if (target.kind === "slide") {
    if (target.id === sourceId) return doc
    const targetIndex = nodes.findIndex((node) => node.id === target.id && node.type === "slide")
    if (targetIndex < 0) return doc
    nodes.splice(targetIndex, 0, source)
    return { ...doc, nodes }
  }

  let start = 0
  if (target.sectionId !== "root") {
    const sectionIndex = nodes.findIndex((node) => node.id === target.sectionId && node.type === "section")
    if (sectionIndex < 0) return doc
    start = sectionIndex + 1
  }
  let end = start
  while (end < nodes.length && nodes[end].type !== "section") end++
  while (end > start && isBlankLine(nodes[end - 1])) end--
  nodes.splice(end, 0, source)
  return { ...doc, nodes }
}

export function useOutlineEditor(content: string | null) {
  const initial = content ?? ""
  const [state, setState] = useState<EditorState>(() => ({
    doc: parseOutlineDocument(initial),
    base: initial,
    latestSeen: initial,
    past: [],
    future: [],
  }))
  const stateRef = useRef(state)
  stateRef.current = state

  const currentText = useMemo(() => serializeOutline(state.doc), [state.doc])
  const dirty = currentText !== state.base
  const operations = useMemo(() => diffLines(state.base, currentText), [state.base, currentText])
  const stats = useMemo(() => diffStats(operations), [operations])

  useEffect(() => {
    const latest = content ?? ""
    setState((previous) => {
      if (latest === previous.latestSeen) return previous
      const isDirty = serializeOutline(previous.doc) !== previous.base
      if (isDirty) return { ...previous, latestSeen: latest }
      const parsed = reconcileIds(previous.doc, parseOutlineDocument(latest))
      return { doc: parsed, base: latest, latestSeen: latest, past: [], future: [] }
    })
  }, [content])

  const mutate = useCallback((update: (doc: OutlineDocument) => OutlineDocument, record = true) => {
    setState((previous) => {
      const next = update(previous.doc)
      if (next === previous.doc || sameDocument(next, previous.doc)) return previous
      return {
        ...previous,
        doc: next,
        past: record ? [...previous.past.slice(-99), previous.doc] : previous.past,
        future: record ? [] : previous.future,
      }
    })
  }, [])

  const snapshot = useCallback(() => stateRef.current.doc, [])
  const commitSnapshot = useCallback((before: OutlineDocument) => {
    setState((previous) => {
      if (sameDocument(before, previous.doc)) return previous
      return { ...previous, past: [...previous.past.slice(-99), before], future: [] }
    })
  }, [])
  const restoreSnapshot = useCallback((before: OutlineDocument) => {
    setState((previous) => ({ ...previous, doc: before }))
  }, [])

  const undo = useCallback(() => {
    setState((previous) => {
      const prior = previous.past.at(-1)
      if (!prior) return previous
      return {
        ...previous,
        doc: prior,
        past: previous.past.slice(0, -1),
        future: [previous.doc, ...previous.future].slice(0, 100),
      }
    })
  }, [])
  const redo = useCallback(() => {
    setState((previous) => {
      const next = previous.future[0]
      if (!next) return previous
      return {
        ...previous,
        doc: next,
        past: [...previous.past.slice(-99), previous.doc],
        future: previous.future.slice(1),
      }
    })
  }, [])

  const discard = useCallback(() => {
    setState((previous) => ({
      doc: reconcileIds(previous.doc, parseOutlineDocument(previous.latestSeen)),
      base: previous.latestSeen,
      latestSeen: previous.latestSeen,
      past: [],
      future: [],
    }))
  }, [])

  const markSaved = useCallback((text: string) => {
    setState((previous) => ({ ...previous, base: text, latestSeen: text, past: [], future: [] }))
  }, [])

  const updateDeckName = useCallback((value: string) => mutate((doc) => setDeckName(doc, value), false), [mutate])
  const updateSectionTitle = useCallback((id: string, value: string) => mutate((doc) => replaceNode(doc, id, (node) => node.type === "section" ? setSectionTitle(node, value) : node), false), [mutate])
  const updateSlideMessage = useCallback((id: string, value: string) => mutate((doc) => replaceNode(doc, id, (node) => node.type === "slide" ? setSlideMessage(node, value) : node), false), [mutate])
  const updateSubItem = useCallback((id: string, key: SubItemKey, value: string) => mutate((doc) => replaceNode(doc, id, (node) => node.type === "slide" ? setSubItemText(node, key, value) : node), false), [mutate])

  const addSlide = useCallback((sectionId: string) => {
    const slide = newSlide(nextPlaceholderSlug(stateRef.current.doc))
    mutate((doc) => insertAtChapterEnd(doc, sectionId, slide))
    return slide.id
  }, [mutate])

  const duplicateSlide = useCallback((id: string) => {
    const current = stateRef.current.doc
    const index = current.nodes.findIndex((node) => node.id === id && node.type === "slide")
    if (index < 0) return ""
    const source = current.nodes[index] as SlideNode
    const copy: SlideNode = {
      ...source,
      id: newSlide(source.slug).id,
      slug: duplicateSlug(current, source.slug),
      raw: undefined,
      subItems: source.subItems.map((item) => ({ ...item, raw: undefined })),
    }
    mutate((doc) => {
      const sourceIndex = doc.nodes.findIndex((node) => node.id === id && node.type === "slide")
      if (sourceIndex < 0) return doc
      const nodes = [...doc.nodes]
      nodes.splice(sourceIndex + 1, 0, copy)
      return { ...doc, nodes }
    })
    return copy.id
  }, [mutate])

  const deleteSlide = useCallback((id: string) => {
    const removed = stateRef.current.doc.nodes.find((node): node is SlideNode => node.id === id && node.type === "slide") ?? null
    if (removed) mutate((doc) => ({ ...doc, nodes: doc.nodes.filter((node) => node.id !== id) }))
    return removed
  }, [mutate])

  const addSection = useCallback(() => {
    const section = newSection()
    mutate((doc) => {
      const nodes = [...doc.nodes]
      if (nodes.length > 0 && !isBlankLine(nodes.at(-1))) nodes.push(blankLine())
      nodes.push(section, blankLine())
      return { ...doc, nodes }
    })
    return section.id
  }, [mutate])

  const deleteSection = useCallback((id: string) => {
    const removed = stateRef.current.doc.nodes.find((node): node is SectionNode => node.id === id && node.type === "section") ?? null
    if (removed) mutate((doc) => ({ ...doc, nodes: doc.nodes.filter((entry) => entry.id !== id) }))
    return removed
  }, [mutate])

  const nudgeSlide = useCallback((id: string, direction: -1 | 1) => {
    const current = stateRef.current.doc
    const sourceIndex = current.nodes.findIndex((node) => node.id === id && node.type === "slide")
    if (sourceIndex < 0) return false
    let neighbor = sourceIndex + direction
    while (neighbor >= 0 && neighbor < current.nodes.length && current.nodes[neighbor].type !== "slide") neighbor += direction
    if (neighbor < 0 || neighbor >= current.nodes.length) return false
    const neighborId = current.nodes[neighbor].id
    mutate((doc) => {
      const from = doc.nodes.findIndex((node) => node.id === id)
      const to = doc.nodes.findIndex((node) => node.id === neighborId)
      return { ...doc, nodes: arrayMove(doc.nodes, from, to) }
    })
    return true
  }, [mutate])

  const moveSlide = useCallback((id: string, target: SlideDropTarget) => {
    mutate((doc) => moveSlideInDocument(doc, id, target), false)
  }, [mutate])

  return {
    doc: state.doc,
    base: state.base,
    latestSeen: state.latestSeen,
    currentText,
    operations,
    stats,
    dirty,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    snapshot,
    commitSnapshot,
    restoreSnapshot,
    undo,
    redo,
    discard,
    markSaved,
    updateDeckName,
    updateSectionTitle,
    updateSlideMessage,
    updateSubItem,
    addSlide,
    duplicateSlide,
    deleteSlide,
    addSection,
    deleteSection,
    nudgeSlide,
    moveSlide,
  }
}

export type OutlineEditor = ReturnType<typeof useOutlineEditor>
