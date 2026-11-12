// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewProvider — the single owner of the comment tool's state on the deck and style screens.
 *
 * The preview (SlideCarousel → ReviewSlideLayer / ReviewCommentCard) and the chat (draft bar,
 * request card, send) both read and change it through `useReview()`, which returns null on
 * screens without a provider so those components render nothing extra.
 *
 * State: tool on/off, unsent frames (persisted per deck in localStorage with a sequence that
 * only grows), selection, the open card, hover, mention highlight and one undo slot for the
 * last delete. A frame keeps its place whether or not it has a comment; only an explicit delete
 * removes it, and Esc on a frame just drawn cancels it. Sent frames leave the canvas once the
 * request is created. Pure rules live in `@/lib/review/*`. Changing deck resets everything
 * except whether the hint was seen. Nothing here reads the review files.
 *
 * Frames are keyed by their name (`A`).
 *
 * The deck screen sends a request through the API, which writes a review file and returns the
 * chat message (`createReview`); the style screen passes `createRequest`, which builds the
 * message in the browser (no file).
 */

"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import { toast } from "sonner"
import { useTranslations } from "next-intl"
import { createReview } from "@/services/deckService"
import { DEFAULT_SIZE, roundRect, type Rect, type SlideSize } from "@/lib/review/geometry"
import { loadDrafts, saveDrafts, type DraftFrame } from "@/lib/review/drafts"
import { frameName, nextSeq } from "@/lib/review/naming"
import { MENTION_RE, stripWhitespace, type ReviewSubmission } from "@/lib/review/schema"

export interface EditorState {
  key: string
  /** True for a frame just drawn: cancelling its card (Esc, ×) removes it without undo. */
  isNew: boolean
}

export interface FrameLookup { frame: DraftFrame; index: number }

export interface ReviewContextValue {
  enabled: boolean
  deckId: string | null
  slugs: string[]
  slideSize: SlideSize
  agentBusy: boolean
  toolOn: boolean
  hintSeen: boolean
  drafts: DraftFrame[]
  /** Drafts on a slide that exists: what `submit` sends. */
  readyDrafts: DraftFrame[]
  /** Whether `submit(note)` has something to ask for: a ready draft with a comment, or a note. */
  canSubmit: (note: string) => boolean
  selected: string | null
  editor: EditorState | null
  peek: string | null
  highlight: string | null
  canUndo: boolean
  setToolOn: (on: boolean) => void
  toggleTool: () => void
  addFrame: (slide: string, rect: Rect) => string
  updateRect: (name: string, rect: Rect) => void
  commitText: (name: string, text: string) => void
  deleteFrame: (name: string) => void
  undoDelete: () => void
  select: (key: string | null) => void
  openEditor: (key: string, isNew?: boolean) => void
  closeEditor: (save: boolean) => void
  /** The open editor's current (unsaved) text; the card reports every change. */
  setEditorText: (text: string) => void
  setPeek: (key: string | null) => void
  setHighlight: (key: string | null) => void
  focusFrame: (key: string) => void
  lookup: (key: string) => FrameLookup | null
  /**
   * Create the request from the ready drafts (they leave the drafts and the canvas); resolves
   * to the chat message to send and `restore`, which puts the sent frames back into the drafts
   * when the chat send fails.
   */
  submit: (note: string) => Promise<SubmittedReview>
  /** A frame was moved or resized on screen (the card follows it). */
  notifyFrameMoved: () => void
  onFrameMoved: (listener: () => void) => () => void
  setDragging: (dragging: boolean) => void
  isDragging: () => boolean
}

export interface SubmittedReview {
  id: string
  message: string
  restore: () => void
}

/** Names mentioned as `@X` in `text`. */
export function mentionedNames(text: string): string[] {
  return [...text.matchAll(MENTION_RE)].map(m => m[1])
}

/** DOM element of the frame `key` on the canvas, if rendered. */
export function frameElement(key: string): HTMLElement | null {
  if (typeof document === "undefined") return null
  return document.querySelector<HTMLElement>(`[data-review-frame="${key.replace(/["\\]/g, "")}"]`)
}

const ReviewContext = createContext<ReviewContextValue | null>(null)

/** The comment tool's state, or null on screens without a ReviewProvider. */
export function useReview(): ReviewContextValue | null {
  return useContext(ReviewContext)
}

interface Core {
  /** undefined until the first load (keeps localStorage out of the server render). */
  deckId: string | null | undefined
  seq: number
  drafts: DraftFrame[]
  toolOn: boolean
  selected: string | null
  editor: EditorState | null
  peek: string | null
  highlight: string | null
  undo: { frame: DraftFrame; index: number } | null
}

function initCore(deckId: string | null | undefined): Core {
  const stored = deckId ? loadDrafts(deckId) : { seq: 0, frames: [] }
  return {
    deckId, seq: stored.seq, drafts: stored.frames, toolOn: false, selected: null, editor: null,
    peek: null, highlight: null, undo: null,
  }
}

const UNDO_MS = 5000
const FOCUS_OPEN_DELAY_MS = 380

export interface ReviewProviderProps {
  /** Id of the surface the drafts belong to (a deck id, or `style:<name>`); the drafts' storage key. */
  deckId: string | null
  slugs: string[]
  slideSize?: SlideSize
  enabled: boolean
  agentBusy: boolean
  openChat: () => void
  idToken?: string
  /** Builds the request in place of `createReview` (the API review file). */
  createRequest?: (submission: ReviewSubmission) => Promise<{ id: string; message: string }>
  children: ReactNode
}

export function ReviewProvider({ deckId, slugs, slideSize, enabled, agentBusy, openChat, idToken, createRequest, children }: ReviewProviderProps) {
  const t = useTranslations("review")
  const [core, setCore] = useState<Core>(() => initCore(undefined))
  const coreRef = useRef(core)
  const [hintSeen, setHintSeen] = useState(false)

  const size = useMemo<SlideSize>(() => (
    slideSize && slideSize.width > 0 && slideSize.height > 0 ? { width: slideSize.width, height: slideSize.height } : DEFAULT_SIZE
  ), [slideSize])
  const slugKey = slugs.join(" ")
  const stableSlugs = useMemo(() => (slugKey ? slugKey.split(" ") : []), [slugKey])

  // Latest props for callbacks that outlive a render (fetches, timers).
  const live = useRef({ openChat, idToken, slugs: stableSlugs, size, t, createRequest })
  useEffect(() => { live.current = { openChat, idToken, slugs: stableSlugs, size, t, createRequest } })

  const editorText = useRef<string | null>(null)
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const undoToast = useRef<string | number | null>(null)
  const moveListeners = useRef(new Set<() => void>())
  const dragging = useRef(false)
  // Late-bound callback for the undo toast.
  const undoDeleteRef = useRef<() => void>(() => {})

  /** Apply a state change synchronously (coreRef is always current) and persist drafts. */
  const update = useCallback((fn: (c: Core) => Core) => {
    const prev = coreRef.current
    const next = fn(prev)
    if (next === prev) return
    coreRef.current = next
    if (next.deckId && next.deckId === prev.deckId && (next.drafts !== prev.drafts || next.seq !== prev.seq)) {
      saveDrafts(next.deckId, { seq: next.seq, frames: next.drafts })
    }
    setCore(next)
  }, [])

  const clearUndo = useCallback(() => {
    if (undoTimer.current) clearTimeout(undoTimer.current)
    undoTimer.current = null
    if (undoToast.current !== null) toast.dismiss(undoToast.current)
    undoToast.current = null
  }, [])

  // Deck change (and first mount): load that deck's drafts, drop everything else.
  useEffect(() => {
    if (coreRef.current.deckId === deckId) return
    clearUndo()
    editorText.current = null
    update(() => initCore(deckId))
  }, [deckId, update, clearUndo])

  useEffect(() => () => {
    if (undoTimer.current) clearTimeout(undoTimer.current)
  }, [])

  /* ── Derived ── */
  const readyDrafts = useMemo(() => {
    const slugSet = new Set(stableSlugs)
    return core.drafts.filter(d => slugSet.has(d.slide))
  }, [core.drafts, stableSlugs])

  const canSubmit = useCallback((note: string) => (
    readyDrafts.length > 0 && (readyDrafts.some(d => stripWhitespace(d.text)) || !!stripWhitespace(note))
  ), [readyDrafts])

  const lookup = useCallback((key: string): FrameLookup | null => {
    const c = coreRef.current
    const index = c.drafts.findIndex(d => d.name === key)
    return index >= 0 ? { frame: c.drafts[index], index } : null
  // core is read through coreRef; re-create when drafts change so consumers re-render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [core.drafts])

  /* ── Frames ── */
  const deleteFrame = useCallback((name: string) => {
    const c = coreRef.current
    const index = c.drafts.findIndex(d => d.name === name)
    if (index < 0) return
    const frame = c.drafts[index]
    const rest = c.drafts.filter((_, i) => i !== index)
    if (c.editor?.key === name) editorText.current = null
    update(cur => ({
      ...cur, drafts: rest, undo: { frame, index },
      selected: cur.selected === name ? null : cur.selected,
      editor: cur.editor?.key === name ? null : cur.editor,
      peek: cur.peek === name ? null : cur.peek,
    }))
    clearUndo()
    const refs = rest.filter(d => mentionedNames(d.text).includes(name)).map(d => d.name)
    const { t: tr } = live.current
    const message = refs.length ? tr("deletedReferenced", { name, refs: refs.join(", ") }) : tr("deleted", { name })
    undoToast.current = toast(message, {
      duration: UNDO_MS,
      action: { label: tr("undo"), onClick: () => undoDeleteRef.current() },
    })
    undoTimer.current = setTimeout(() => {
      undoTimer.current = null
      undoToast.current = null
      update(cur => (cur.undo?.frame === frame ? { ...cur, undo: null } : cur))
    }, UNDO_MS)
  }, [update, clearUndo])

  const undoDelete = useCallback(() => {
    const u = coreRef.current.undo
    if (!u) return
    clearUndo()
    update(cur => {
      if (cur.drafts.some(d => d.name === u.frame.name)) return { ...cur, undo: null }
      const drafts = [...cur.drafts]
      drafts.splice(Math.min(u.index, drafts.length), 0, u.frame)
      return { ...cur, drafts, undo: null, selected: u.frame.name }
    })
  }, [update, clearUndo])
  useEffect(() => { undoDeleteRef.current = undoDelete }, [undoDelete])

  /** Apply `text` to draft `name`, stripped; an empty comment is kept (the frame stays). */
  const commitText = useCallback((name: string, text: string) => {
    const frame = coreRef.current.drafts.find(d => d.name === name)
    if (!frame) return
    const value = stripWhitespace(text)
    if (value !== frame.text) update(cur => ({ ...cur, drafts: cur.drafts.map(d => (d.name === name ? { ...d, text: value } : d)) }))
  }, [update])

  const closeEditor = useCallback((save: boolean) => {
    const c = coreRef.current
    const ed = c.editor
    if (!ed) return
    const typed = editorText.current
    editorText.current = null
    // Cancelling the card of a frame just drawn cancels the frame (no undo).
    if (!save && ed.isNew) {
      update(cur => ({
        ...cur, editor: null, drafts: cur.drafts.filter(d => d.name !== ed.key),
        selected: cur.selected === ed.key ? null : cur.selected,
        peek: cur.peek === ed.key ? null : cur.peek,
      }))
      return
    }
    update(cur => ({ ...cur, editor: null }))
    // Cancelling keeps the saved text.
    if (save && typed !== null) commitText(ed.key, typed)
  }, [update, commitText])

  const openEditor = useCallback((key: string, isNew = false) => {
    const c = coreRef.current
    if (c.editor && c.editor.key !== key) closeEditor(true)
    if (coreRef.current.editor?.key === key) return
    editorText.current = null
    update(cur => ({ ...cur, editor: { key, isNew }, selected: key, peek: null }))
  }, [update, closeEditor])

  const addFrame = useCallback((slide: string, rect: Rect) => {
    const c = coreRef.current
    if (c.editor) closeEditor(true)
    const name = frameName(coreRef.current.seq)
    const first = coreRef.current.drafts.length === 0
    editorText.current = null
    update(cur => ({
      ...cur, seq: cur.seq + 1, drafts: [...cur.drafts, { name, slide, rect, text: "" }],
      selected: name, editor: { key: name, isNew: true }, peek: null,
    }))
    setHintSeen(true)
    if (first) live.current.openChat() // R4.4: the drafts collect in the chat input
    return name
  }, [update, closeEditor])

  const updateRect = useCallback((name: string, rect: Rect) => {
    update(cur => ({ ...cur, drafts: cur.drafts.map(d => (d.name === name ? { ...d, rect } : d)) }))
  }, [update])

  const select = useCallback((key: string | null) => {
    update(cur => (cur.selected === key ? cur : { ...cur, selected: key }))
  }, [update])

  const setToolOn = useCallback((on: boolean) => {
    if (!on) closeEditor(true)
    update(cur => (cur.toolOn === on ? cur : { ...cur, toolOn: on, selected: on ? cur.selected : null, peek: null }))
  }, [update, closeEditor])
  const toggleTool = useCallback(() => setToolOn(!coreRef.current.toolOn), [setToolOn])

  const setEditorText = useCallback((text: string) => { editorText.current = text }, [])
  const setPeek = useCallback((key: string | null) => update(cur => (cur.peek === key ? cur : { ...cur, peek: key })), [update])
  const setHighlight = useCallback((key: string | null) => update(cur => (cur.highlight === key ? cur : { ...cur, highlight: key })), [update])

  const focusFrame = useCallback((key: string) => {
    closeEditor(true)
    // HTML decks show the player while the tool is off; the frames appear in the stacked view.
    if (!frameElement(key) && !coreRef.current.toolOn) setToolOn(true)
    select(key)
    const attempt = (n: number) => {
      const el = frameElement(key)
      if (!el) {
        if (n < 10) setTimeout(() => attempt(n + 1), 100)
        return
      }
      el.scrollIntoView?.({ behavior: "smooth", block: "center" })
      setTimeout(() => openEditor(key), FOCUS_OPEN_DELAY_MS)
    }
    attempt(0)
  }, [closeEditor, setToolOn, select, openEditor])

  /* ── Change requests ── */
  const submit = useCallback(async (note: string): Promise<SubmittedReview> => {
    closeEditor(true)
    const c = coreRef.current
    const forDeck = c.deckId
    if (!forDeck) throw new Error("No deck is open")
    const { slugs: currentSlugs, size: currentSize, idToken: token, createRequest: build } = live.current
    const slugSet = new Set(currentSlugs)
    const frames = c.drafts.filter(d => slugSet.has(d.slide))
    if (!frames.length) throw new Error("No frames to send")
    if (!frames.some(d => stripWhitespace(d.text)) && !stripWhitespace(note)) throw new Error("No comment or note to send")
    const submission: ReviewSubmission = {
      note: stripWhitespace(note) || null,
      comments: frames.map(d => ({ name: d.name, slide: d.slide, rect: roundRect(d.rect, currentSize), text: stripWhitespace(d.text) })),
    }
    const created = build ? await build(submission) : await createReview(forDeck, submission, token ?? "")
    const sent = new Set(frames.map(f => f.name))
    update(cur => {
      if (cur.deckId !== forDeck) return cur
      return {
        ...cur,
        // Frames on slides that no longer exist go too; frames drawn while sending stay.
        drafts: cur.drafts.filter(d => !sent.has(d.name) && slugSet.has(d.slide)),
        seq: Math.max(cur.seq, nextSeq(sent)),
        selected: null, editor: null, peek: null, toolOn: false,
      }
    })
    // Back in front of any frame drawn since (names are never reused, so none collide).
    const back = (drafts: DraftFrame[]) => {
      const names = new Set(drafts.map(d => d.name))
      return [...frames.filter(f => !names.has(f.name)), ...drafts]
    }
    const restore = () => {
      if (coreRef.current.deckId === forDeck) {
        update(cur => ({ ...cur, drafts: back(cur.drafts) }))
        return
      }
      const stored = loadDrafts(forDeck)
      saveDrafts(forDeck, { seq: stored.seq, frames: back(stored.frames) })
    }
    return { ...created, restore }
  }, [closeEditor, update])

  /* ── Canvas plumbing (no re-render) ── */
  const notifyFrameMoved = useCallback(() => { for (const l of moveListeners.current) l() }, [])
  const onFrameMoved = useCallback((listener: () => void) => {
    moveListeners.current.add(listener)
    return () => { moveListeners.current.delete(listener) }
  }, [])
  const setDragging = useCallback((v: boolean) => { dragging.current = v }, [])
  const isDragging = useCallback(() => dragging.current, [])

  const value = useMemo<ReviewContextValue>(() => ({
    enabled, deckId: deckId ?? null, slugs: stableSlugs, slideSize: size, agentBusy,
    toolOn: core.toolOn, hintSeen, drafts: core.drafts, readyDrafts, canSubmit, selected: core.selected, editor: core.editor,
    peek: core.peek, highlight: core.highlight, canUndo: core.undo !== null,
    setToolOn, toggleTool, addFrame, updateRect, commitText, deleteFrame, undoDelete, select, openEditor, closeEditor,
    setEditorText, setPeek, setHighlight, focusFrame, lookup, submit,
    notifyFrameMoved, onFrameMoved, setDragging, isDragging,
  }), [
    enabled, deckId, stableSlugs, size, agentBusy, core, hintSeen, readyDrafts, canSubmit,
    setToolOn, toggleTool, addFrame, updateRect, commitText, deleteFrame, undoDelete, select, openEditor, closeEditor,
    setEditorText, setPeek, setHighlight, focusFrame, lookup, submit,
    notifyFrameMoved, onFrameMoved, setDragging, isDragging,
  ])

  return <ReviewContext.Provider value={value}>{children}</ReviewContext.Provider>
}
