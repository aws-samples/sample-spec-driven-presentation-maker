// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewProvider — the single owner of the comment tool's state on the deck screen.
 *
 * The preview (SlideCarousel → ReviewSlideLayer / ReviewCommentCard) and the chat (draft bar,
 * request card, send) both read and change it through `useReview()`, which returns null on
 * screens without a provider so those components render nothing extra.
 *
 * State: tool on/off, unsent frames (persisted per deck in localStorage with a sequence that
 * only grows), selection, the open card, hover, mention highlight, one undo slot for the last
 * delete, and the review requests loaded from chat markers (status and replies). Pure rules
 * live in `@/lib/review/*`. Changing deck resets everything except whether the hint was seen.
 *
 * Frame keys: a draft is keyed by its name (`A`); a sent comment by `<requestId>/<name>`
 * (`sentFrameKey`), so names reused across browsers never collide on the canvas.
 */

"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import { toast } from "sonner"
import { useTranslations } from "next-intl"
import { createReview, getReview } from "@/services/deckService"
import { DEFAULT_SIZE, roundRect, type Rect, type SlideSize } from "@/lib/review/geometry"
import { loadDrafts, saveDrafts, type DraftFrame } from "@/lib/review/drafts"
import { frameName, nextSeq } from "@/lib/review/naming"
import { MENTION_RE, isReviewId, type ReviewRequest, type ReviewSubmission } from "@/lib/review/schema"

export type RequestEntry = ReviewRequest | "loading" | "error"
/** Status of a sent comment that is still open: 対応中 while the agent works on the latest request. */
export type SentStatus = "sent" | "working"

export interface SentFrame {
  key: string
  requestId: string
  name: string
  slide: string
  rect: Rect
  /** Slide size the rect was written in (the request's `slide_size`). */
  size: SlideSize
  text: string
}

export interface EditorState {
  key: string
  /** True for a frame just drawn: closing it without text removes it without undo. */
  isNew: boolean
}

export type FrameLookup = { kind: "draft"; frame: DraftFrame; index: number } | { kind: "sent"; frame: SentFrame }

export interface ReviewContextValue {
  enabled: boolean
  deckId: string | null
  slugs: string[]
  slideSize: SlideSize
  agentBusy: boolean
  toolOn: boolean
  hintSeen: boolean
  drafts: DraftFrame[]
  /** Drafts with a comment on a slide that exists: what `submit` sends. */
  readyDrafts: DraftFrame[]
  selected: string | null
  editor: EditorState | null
  peek: string | null
  highlight: string | null
  canUndo: boolean
  requests: ReadonlyMap<string, RequestEntry>
  openSent: SentFrame[]
  latestRequestId: string | null
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
  statusOf: (requestId: string) => SentStatus
  track: (deckId: string, ids: string[]) => void
  refresh: () => void
  submit: (note: string) => Promise<string>
  /** Requests whose chat message did not reach the agent; their card offers a retry. */
  failed: ReadonlySet<string>
  /** The chat send of request `id` failed; `retry` sends the same message again. */
  markFailed: (id: string, retry: () => void) => void
  retry: (id: string) => void
  /** A frame was moved or resized on screen (the card follows it). */
  notifyFrameMoved: () => void
  onFrameMoved: (listener: () => void) => () => void
  setDragging: (dragging: boolean) => void
  isDragging: () => boolean
}

export function sentFrameKey(requestId: string, name: string): string {
  return `${requestId}/${name}`
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
  requests: Map<string, RequestEntry>
}

function initCore(deckId: string | null | undefined): Core {
  const stored = deckId ? loadDrafts(deckId) : { seq: 0, frames: [] }
  return {
    deckId, seq: stored.seq, drafts: stored.frames, toolOn: false, selected: null, editor: null,
    peek: null, highlight: null, undo: null, requests: new Map(),
  }
}

const UNDO_MS = 5000
const REFRESH_MS = 1500
const FOCUS_OPEN_DELAY_MS = 380

export interface ReviewProviderProps {
  deckId: string | null
  slugs: string[]
  slideSize?: SlideSize
  enabled: boolean
  agentBusy: boolean
  openChat: () => void
  idToken?: string
  children: ReactNode
}

export function ReviewProvider({ deckId, slugs, slideSize, enabled, agentBusy, openChat, idToken, children }: ReviewProviderProps) {
  const t = useTranslations("review")
  const [core, setCore] = useState<Core>(() => initCore(undefined))
  const coreRef = useRef(core)
  const [hintSeen, setHintSeen] = useState(false)
  const [failed, setFailed] = useState<ReadonlySet<string>>(() => new Set())
  const retries = useRef(new Map<string, () => void>())

  const size = useMemo<SlideSize>(() => (
    slideSize && slideSize.width > 0 && slideSize.height > 0 ? { width: slideSize.width, height: slideSize.height } : DEFAULT_SIZE
  ), [slideSize])
  const slugKey = slugs.join(" ")
  const stableSlugs = useMemo(() => (slugKey ? slugKey.split(" ") : []), [slugKey])

  // Latest props for callbacks that outlive a render (fetches, timers).
  const live = useRef({ openChat, idToken, slugs: stableSlugs, size, t })
  useEffect(() => { live.current = { openChat, idToken, slugs: stableSlugs, size, t } })

  const editorText = useRef<string | null>(null)
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const undoToast = useRef<string | number | null>(null)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastRefresh = useRef(0)
  const moveListeners = useRef(new Set<() => void>())
  const dragging = useRef(false)
  // Late-bound callbacks for the undo toast and the trailing refresh.
  const undoDeleteRef = useRef<() => void>(() => {})
  const refreshRef = useRef<() => void>(() => {})

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
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    refreshTimer.current = null
    editorText.current = null
    retries.current.clear()
    setFailed(new Set())
    update(() => initCore(deckId))
  }, [deckId, update, clearUndo])

  useEffect(() => () => {
    if (undoTimer.current) clearTimeout(undoTimer.current)
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
  }, [])

  /* ── Derived ── */
  const openSent = useMemo<SentFrame[]>(() => {
    const slugSet = new Set(stableSlugs)
    const out: SentFrame[] = []
    for (const [requestId, entry] of core.requests) {
      if (typeof entry !== "object") continue
      const [w, h] = entry.slide_size
      for (const c of entry.comments) {
        if (c.status !== "open" || !slugSet.has(c.slide)) continue
        out.push({ key: sentFrameKey(requestId, c.name), requestId, name: c.name, slide: c.slide, rect: c.rect, size: { width: w, height: h }, text: c.text })
      }
    }
    return out
  }, [core.requests, stableSlugs])

  const latestRequestId = useMemo(() => {
    let latest: string | null = null
    for (const id of core.requests.keys()) if (!latest || id > latest) latest = id
    return latest
  }, [core.requests])

  const readyDrafts = useMemo(() => {
    const slugSet = new Set(stableSlugs)
    return core.drafts.filter(d => d.text.trim() && slugSet.has(d.slide))
  }, [core.drafts, stableSlugs])

  const statusOf = useCallback((requestId: string): SentStatus => (
    requestId === latestRequestId && agentBusy ? "working" : "sent"
  ), [latestRequestId, agentBusy])

  const lookup = useCallback((key: string): FrameLookup | null => {
    const c = coreRef.current
    const index = c.drafts.findIndex(d => d.name === key)
    if (index >= 0) return { kind: "draft", frame: c.drafts[index], index }
    const sent = openSent.find(f => f.key === key)
    return sent ? { kind: "sent", frame: sent } : null
  // core is read through coreRef; re-create when drafts change so consumers re-render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSent, core.drafts])

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

  /**
   * Apply `text` to draft `name` (R2.6): a comment is required, so an empty text removes a
   * frame that never had one (no undo) and deletes one that had (with undo).
   */
  const commitText = useCallback((name: string, text: string) => {
    const c = coreRef.current
    const frame = c.drafts.find(d => d.name === name)
    if (!frame) return
    const value = text.trim()
    if (value) {
      if (value !== frame.text) update(cur => ({ ...cur, drafts: cur.drafts.map(d => (d.name === name ? { ...d, text: value } : d)) }))
      return
    }
    if (!frame.text.trim()) {
      update(cur => ({
        ...cur, drafts: cur.drafts.filter(d => d.name !== name),
        selected: cur.selected === name ? null : cur.selected,
        peek: cur.peek === name ? null : cur.peek,
      }))
      return
    }
    deleteFrame(name)
  }, [update, deleteFrame])

  const closeEditor = useCallback((save: boolean) => {
    const c = coreRef.current
    const ed = c.editor
    if (!ed) return
    const typed = editorText.current
    editorText.current = null
    update(cur => ({ ...cur, editor: null }))
    const frame = c.drafts.find(d => d.name === ed.key)
    if (!frame) return
    // Cancelling keeps the saved text; a frame left without any text is removed.
    commitText(frame.name, save && typed !== null ? typed : frame.text)
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

  /* ── Review requests ── */
  const storeRequest = useCallback((forDeck: string, id: string, entry: RequestEntry, keepLoaded: boolean) => {
    update(cur => {
      if (cur.deckId !== forDeck) return cur
      const prev = cur.requests.get(id)
      if (keepLoaded && typeof entry !== "object" && typeof prev === "object") return cur
      const requests = new Map(cur.requests).set(id, entry)
      const seq = typeof entry === "object" ? Math.max(cur.seq, nextSeq(entry.comments.map(x => x.name))) : cur.seq
      return { ...cur, requests, seq }
    })
  }, [update])

  const fetchRequest = useCallback((forDeck: string, id: string, keepLoaded: boolean) => {
    getReview(forDeck, id, live.current.idToken ?? "").then(
      (r) => storeRequest(forDeck, id, r ?? "error", keepLoaded),
      () => storeRequest(forDeck, id, "error", keepLoaded),
    )
  }, [storeRequest])

  const track = useCallback((forDeck: string, ids: string[]) => {
    const c = coreRef.current
    if (!c.deckId || forDeck !== c.deckId) return
    const fresh = [...new Set(ids)].filter(id => isReviewId(id) && !c.requests.has(id))
    if (!fresh.length) return
    update(cur => {
      const requests = new Map(cur.requests)
      for (const id of fresh) requests.set(id, "loading")
      return { ...cur, requests }
    })
    for (const id of fresh) fetchRequest(forDeck, id, false)
  }, [update, fetchRequest])

  const refresh = useCallback(() => {
    const wait = lastRefresh.current + REFRESH_MS - Date.now()
    if (wait > 0) {
      if (!refreshTimer.current) refreshTimer.current = setTimeout(() => { refreshTimer.current = null; refreshRef.current() }, wait)
      return
    }
    lastRefresh.current = Date.now()
    const c = coreRef.current
    if (!c.deckId) return
    for (const [id, entry] of c.requests) {
      if (typeof entry === "object" && entry.comments.some(x => x.status === "open")) fetchRequest(c.deckId, id, true)
    }
  }, [fetchRequest])
  useEffect(() => { refreshRef.current = refresh }, [refresh])

  const submit = useCallback(async (note: string): Promise<string> => {
    closeEditor(true)
    const c = coreRef.current
    const forDeck = c.deckId
    if (!forDeck) throw new Error("No deck is open")
    const { slugs: currentSlugs, size: currentSize, idToken: token } = live.current
    const slugSet = new Set(currentSlugs)
    const frames = c.drafts.filter(d => d.text.trim() && slugSet.has(d.slide))
    if (!frames.length) throw new Error("No comments to send")
    const submission: ReviewSubmission = {
      note: note.trim() || null,
      comments: frames.map(d => ({ name: d.name, slide: d.slide, rect: roundRect(d.rect, currentSize), text: d.text.trim() })),
    }
    const review = await createReview(forDeck, submission, token ?? "")
    const sent = new Set(frames.map(f => f.name))
    update(cur => {
      if (cur.deckId !== forDeck) return cur
      return {
        ...cur,
        // Frames on slides that no longer exist go too; frames drawn while sending stay.
        drafts: cur.drafts.filter(d => !sent.has(d.name) && slugSet.has(d.slide)),
        seq: Math.max(cur.seq, nextSeq(sent)),
        selected: null, editor: null, peek: null, toolOn: false,
        requests: new Map(cur.requests).set(review.id, review),
      }
    })
    return review.id
  }, [closeEditor, update])

  const markFailed = useCallback((id: string, retry: () => void) => {
    retries.current.set(id, retry)
    setFailed(cur => new Set(cur).add(id))
  }, [])

  const retry = useCallback((id: string) => {
    const fn = retries.current.get(id)
    retries.current.delete(id)
    setFailed(cur => {
      if (!cur.has(id)) return cur
      const next = new Set(cur)
      next.delete(id)
      return next
    })
    fn?.()
  }, [])

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
    toolOn: core.toolOn, hintSeen, drafts: core.drafts, readyDrafts, selected: core.selected, editor: core.editor,
    peek: core.peek, highlight: core.highlight, canUndo: core.undo !== null, requests: core.requests,
    openSent, latestRequestId,
    setToolOn, toggleTool, addFrame, updateRect, commitText, deleteFrame, undoDelete, select, openEditor, closeEditor,
    setEditorText, setPeek, setHighlight, focusFrame, lookup, statusOf, track, refresh, submit,
    failed, markFailed, retry,
    notifyFrameMoved, onFrameMoved, setDragging, isDragging,
  }), [
    enabled, deckId, stableSlugs, size, agentBusy, core, hintSeen, readyDrafts, openSent, latestRequestId,
    setToolOn, toggleTool, addFrame, updateRect, commitText, deleteFrame, undoDelete, select, openEditor, closeEditor,
    setEditorText, setPeek, setHighlight, focusFrame, lookup, statusOf, track, refresh, submit,
    failed, markFailed, retry,
    notifyFrameMoved, onFrameMoved, setDragging, isDragging,
  ])

  return <ReviewContext.Provider value={value}>{children}</ReviewContext.Provider>
}
