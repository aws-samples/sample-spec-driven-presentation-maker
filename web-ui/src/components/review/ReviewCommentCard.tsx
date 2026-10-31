// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ReviewCommentCard — one fixed-position card for hovering a frame (peek) and for opening it
 * (edit for drafts, view for sent comments). Hover → click turns the same card into the
 * editor in place: its height morphs, the header buttons and footer fade in, the border takes
 * the annotation colour. Moving between frames while peeking glides the card over.
 *
 * Placement (mock `placePop`): right of the frame (left when there is no room), top aligned to
 * the frame's tag, clamped inside the nearest `[data-slide-scroller]`. The peek hides on scroll;
 * the open card follows its frame. A pointerdown outside the card and the comment layers saves
 * and closes the editor (R3.3).
 */

"use client"

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import TextareaAutosize from "react-textarea-autosize"
import { useTranslations } from "next-intl"
import { Loader2, Trash2, X } from "lucide-react"
import { useCompositionSafe } from "@/hooks/useCompositionSafe"
import { MentionText } from "@/components/review/MentionText"
import { frameElement, sentFrameKey, useReview, type ReviewContextValue } from "@/components/review/ReviewProvider"
import type { DraftFrame } from "@/lib/review/drafts"

const CARD_WIDTH = 300
const GAP = 12
const PEEK_DELAY_MS = 120
const LEAVE_MS = 110
const MORPH_MS = 230

type Mode = "peek" | "edit" | "view"
interface CardView { key: string; mode: Mode; phase: "enter" | "steady" | "leave"; glide: boolean; reveal: boolean; seq: number }

const ICON_BUTTON = "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background-hover hover:text-foreground"

export function ReviewCommentCard() {
  const review = useReview()
  const t = useTranslations("review")
  const cardRef = useRef<HTMLDivElement>(null)
  const reviewRef = useRef(review)
  useEffect(() => { reviewRef.current = review })

  /* ── What the card should show ── */
  const active = review?.enabled ? review : null
  const targetKey = active ? (active.editor?.key ?? active.peek) : null
  const found = active && targetKey ? active.lookup(targetKey) : null
  const desired: { key: string; mode: Mode } | null = !active || !targetKey || !found ? null
    : !active.editor ? { key: targetKey, mode: "peek" }
      : { key: targetKey, mode: found.kind === "draft" ? "edit" : "view" }
  const desiredSig = desired ? `${desired.key}|${desired.mode}` : ""

  // Derive the card's transition from the change of target (state adjusted during render).
  const [view, setView] = useState<CardView | null>(null)
  const [sig, setSig] = useState("")
  if (sig !== desiredSig) {
    setSig(desiredSig)
    if (!desired) {
      if (view && view.phase !== "leave") setView({ ...view, phase: "leave" })
    } else if (!view || view.phase === "leave") {
      setView({ ...desired, phase: "enter", glide: false, reveal: false, seq: (view?.seq ?? 0) + 1 })
    } else if (view.key !== desired.key) {
      // Peek → peek glides over; opening another frame's card starts afresh.
      const glide = view.mode === "peek" && desired.mode === "peek"
      setView({ ...desired, phase: glide ? "steady" : "enter", glide, reveal: false, seq: glide ? view.seq : view.seq + 1 })
    } else {
      // Same frame, peek → open: morph in place.
      setView({ ...desired, phase: "steady", glide: false, reveal: view.mode === "peek", seq: view.seq })
    }
  }

  useEffect(() => {
    if (view?.phase !== "leave") return
    const timer = setTimeout(() => setView((v) => (v?.phase === "leave" ? null : v)), LEAVE_MS)
    return () => clearTimeout(timer)
  }, [view])

  /* ── Placement ── */
  const morphing = useRef(false)
  const lastHeight = useRef(0)
  const viewKey = useRef<string | null>(null)
  const place = useCallback(() => {
    const card = cardRef.current
    const key = viewKey.current
    if (!card || !key) return
    const el = frameElement(key)
    if (!el) return
    const b = el.getBoundingClientRect()
    const area = el.closest("[data-slide-scroller]")?.getBoundingClientRect()
    let left = b.right + GAP
    if (left + CARD_WIDTH > window.innerWidth - 8) left = Math.max(8, b.left - CARD_WIDTH - GAP)
    const height = card.offsetHeight
    const minTop = (area ? area.top : 0) + 8
    const maxTop = (area ? area.bottom : window.innerHeight) - height - 8
    card.style.left = `${left}px`
    card.style.top = `${Math.max(minTop, Math.min(b.top - 20, maxTop))}px`
    if (!morphing.current) lastHeight.current = card.getBoundingClientRect().height
  }, [])

  // Height morph between modes (FLIP on height), then place.
  useLayoutEffect(() => {
    viewKey.current = view && view.phase !== "leave" ? view.key : null
    const card = cardRef.current
    if (!card || !view || view.phase === "leave") { if (!view) lastHeight.current = 0; return }
    const h0 = lastHeight.current
    card.style.height = ""
    const h1 = card.getBoundingClientRect().height
    let timer: ReturnType<typeof setTimeout> | undefined
    if (view.phase !== "enter" && h0 && Math.abs(h1 - h0) >= 1) {
      morphing.current = true
      card.style.overflow = "hidden"
      card.style.height = `${h0}px`
      void card.offsetHeight
      card.style.height = `${h1}px`
      timer = setTimeout(() => {
        morphing.current = false
        card.style.height = ""
        card.style.overflow = ""
        lastHeight.current = card.getBoundingClientRect().height
      }, MORPH_MS)
    }
    place()
    return () => { if (timer) { clearTimeout(timer); morphing.current = false } }
  }, [view, place])

  // Follow the frame while it is dragged, on resize, and on scroll (the peek hides instead).
  const onFrameMoved = review?.onFrameMoved
  useEffect(() => {
    if (!onFrameMoved) return
    const off = onFrameMoved(place)
    const onResize = () => place()
    const onScroll = () => {
      const r = reviewRef.current
      if (!r) return
      if (r.editor) place()
      else if (r.peek) r.setPeek(null)
    }
    window.addEventListener("resize", onResize)
    document.addEventListener("scroll", onScroll, true)
    return () => { off(); window.removeEventListener("resize", onResize); document.removeEventListener("scroll", onScroll, true) }
  }, [onFrameMoved, place])

  /* ── Hover → peek ── */
  const peekTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hovered = useRef<string | null>(null)
  const noPeek = useRef<string | null>(null)
  const prevEditorKey = useRef<string | null>(null)
  const editorKey = active?.editor?.key ?? null
  useEffect(() => {
    // No instant re-peek under the cursor right after a card closes.
    if (prevEditorKey.current && prevEditorKey.current !== editorKey) noPeek.current = prevEditorKey.current
    prevEditorKey.current = editorKey
  }, [editorKey])

  useEffect(() => {
    const clearTimer = () => { if (peekTimer.current) clearTimeout(peekTimer.current); peekTimer.current = null }
    const onMove = (e: MouseEvent) => {
      const r = reviewRef.current
      if (!r?.enabled) return
      const target = e.target instanceof Element ? e.target : null
      const key = target?.closest("[data-review-frame]")?.getAttribute("data-review-frame") ?? null
      hovered.current = key
      if (noPeek.current && key !== noPeek.current) noPeek.current = null
      if (r.editor) return
      if (!key) { clearTimer(); if (r.peek) r.setPeek(null); return }
      if (key === r.peek || peekTimer.current || r.isDragging() || noPeek.current === key) return
      if (r.peek) { r.setPeek(key); return } // moving between frames switches at once
      peekTimer.current = setTimeout(() => {
        peekTimer.current = null
        const cur = reviewRef.current
        const k = hovered.current
        if (cur && k && !cur.editor && !cur.isDragging() && noPeek.current !== k) cur.setPeek(k)
      }, PEEK_DELAY_MS)
    }
    document.addEventListener("mousemove", onMove)
    return () => { clearTimer(); document.removeEventListener("mousemove", onMove) }
  }, [])

  /* ── Outside pointerdown saves (R3.3) ── */
  const pinned = !!active?.editor
  useEffect(() => {
    if (!pinned) return
    const onDown = (e: PointerEvent) => {
      const el = e.target instanceof Element ? e.target : null
      if (el?.closest("[data-review-card]") || el?.closest("[data-review-layer]")) return
      reviewRef.current?.closeEditor(true)
    }
    document.addEventListener("pointerdown", onDown, true)
    return () => document.removeEventListener("pointerdown", onDown, true)
  }, [pinned])

  if (!review || !view || typeof document === "undefined") return null
  const shown = review.lookup(view.key)
  if (!shown) return null

  const isSent = shown.kind === "sent"
  const name = shown.frame.name
  const slideIndex = review.slugs.indexOf(shown.frame.slide)
  const status = isSent ? review.statusOf(shown.frame.requestId) : null
  const reveal = view.reveal ? "review-reveal" : ""
  const draftNames = new Set(review.drafts.filter(d => d.text.trim()).map(d => d.name))
  const sentRequest = isSent ? review.requests.get(shown.frame.requestId) : undefined
  const sentNames = new Set(typeof sentRequest === "object" ? sentRequest.comments.map(c => c.name) : [])
  const exists = (n: string) => (isSent ? sentNames.has(n) : draftNames.has(n))
  const keyFor = isSent ? (n: string) => sentFrameKey((shown.frame as { requestId: string }).requestId, n) : undefined
  const mode = view.mode

  return createPortal(
    <div
      key={`card-${view.seq}`}
      ref={cardRef}
      data-review-card
      className="review-card"
      data-mode={mode}
      data-phase={view.phase}
      data-glide={view.glide}
      role={mode === "peek" ? "tooltip" : "dialog"}
      aria-label={t("frameLabel", { name })}
    >
      <div className="flex h-9 items-center gap-2 pl-3 pr-1.5">
        <span className="inline-flex h-5 flex-none items-center rounded-[5px] bg-human px-[7px] text-xs font-bold text-human-ink">{name}</span>
        {slideIndex >= 0 && <span className="text-xs text-muted-foreground">{t("slide", { n: slideIndex + 1 })}</span>}
        <span className="flex-1" />
        {status && (mode !== "edit") && (
          <span className={`flex items-center gap-1 pr-1.5 text-xs text-muted-foreground ${reveal}`}>
            {status === "working" && <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden />}
            {t(`status.${status}`)}
          </span>
        )}
        {mode === "edit" && !review.editor?.isNew && (
          <button type="button" className={`${ICON_BUTTON} ${reveal}`} aria-label={t("deleteLabel")} title={t("deleteLabel")} onClick={() => review.deleteFrame(name)}>
            <Trash2 className="h-[15px] w-[15px]" />
          </button>
        )}
        {mode !== "peek" && (
          <button type="button" className={`${ICON_BUTTON} ${reveal}`} aria-label={t("closeLabel")} title={t("closeLabel")} onClick={() => review.closeEditor(false)}>
            <X className="h-[15px] w-[15px]" />
          </button>
        )}
      </div>
      {mode === "edit" && shown.kind === "draft" && view.phase !== "leave" ? (
        <CardEditor key={view.key} review={review} frame={shown.frame} reveal={view.reveal} onResize={place} />
      ) : (
        <div className={`whitespace-pre-wrap break-words px-3 pb-2.5 text-sm leading-relaxed ${mode === "peek" ? "line-clamp-6" : ""}`}>
          <MentionText text={shown.frame.text} exists={exists} keyFor={keyFor} />
        </div>
      )}
    </div>,
    document.body,
  )
}

interface CardEditorProps {
  review: ReviewContextValue
  frame: DraftFrame
  reveal: boolean
  onResize: () => void
}

/** The draft's textarea with `@` completion of the other drafts (R3.4). */
function CardEditor({ review, frame, reveal, onResize }: CardEditorProps) {
  const t = useTranslations("review")
  const [value, setValue] = useState(frame.text)
  const [caret, setCaret] = useState(frame.text.length)
  const [mi, setMi] = useState(0)
  const ref = useRef<HTMLTextAreaElement>(null)
  const pendingCaret = useRef<number | null>(null)
  const { onCompositionStart, onCompositionEnd, getIsComposing } = useCompositionSafe()
  const { setEditorText, closeEditor, select } = review

  useEffect(() => {
    setEditorText(frame.text)
    const ta = ref.current
    if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length) }
  // Mount only: the editor starts from the saved text once per opening.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useLayoutEffect(() => {
    const ta = ref.current
    if (ta && pendingCaret.current !== null) {
      ta.focus()
      ta.setSelectionRange(pendingCaret.current, pendingCaret.current)
      pendingCaret.current = null
    }
    onResize()
  }, [value, onResize])

  const query = value.slice(0, caret).match(/@([A-Za-z]*)$/)
  const candidates = query
    ? review.drafts.filter(d => d.name !== frame.name && d.text.trim() && d.name.startsWith(query[1].toUpperCase()))
    : []
  const active = Math.min(mi, Math.max(0, candidates.length - 1))

  const change = (next: string, pos: number) => {
    setValue(next)
    setCaret(pos)
    setEditorText(next)
  }
  const insertMention = (name: string) => {
    const before = value.slice(0, caret).replace(/@([A-Za-z]*)$/, `@${name} `)
    const next = before + value.slice(caret)
    pendingCaret.current = before.length
    change(next, before.length)
    setMi(0)
  }

  return (
    <>
      <TextareaAutosize
        ref={ref}
        minRows={1}
        maxRows={8}
        value={value}
        placeholder={t("placeholder")}
        aria-label={t("frameLabel", { name: frame.name })}
        className="block max-h-[200px] min-h-8 w-full resize-none overflow-auto border-0 bg-transparent px-3 pb-1 text-sm leading-relaxed outline-none placeholder:text-muted-foreground"
        onChange={(e) => { change(e.target.value, e.target.selectionStart); setMi(0) }}
        // While a mention insert is pending, the DOM still holds the old caret.
        onSelect={(e) => { if (pendingCaret.current === null) setCaret(e.currentTarget.selectionStart) }}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={onCompositionEnd}
        onKeyDown={(e) => {
          if (getIsComposing(e)) return // IME: Enter confirms the conversion, it must not save
          if (candidates.length) {
            if (e.key === "ArrowDown") { e.preventDefault(); setMi((active + 1) % candidates.length); return }
            if (e.key === "ArrowUp") { e.preventDefault(); setMi((active - 1 + candidates.length) % candidates.length); return }
            if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); insertMention(candidates[active].name); return }
          }
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            closeEditor(true)
            select(null)
            return
          }
          if (e.key === "Escape") {
            e.preventDefault()
            e.stopPropagation()
            closeEditor(false)
          }
        }}
      />
      {candidates.length > 0 && (
        <div role="listbox" aria-label={t("mentionList")} className="mx-2 mb-2 overflow-hidden rounded-lg border border-border-hover bg-background-raised">
          {candidates.map((d, i) => (
            <div
              key={d.name}
              role="option"
              aria-selected={i === active}
              className={`flex cursor-pointer items-center gap-2 px-2 py-1.5 text-sm ${i === active ? "bg-background-hover" : "hover:bg-background-hover"}`}
              onMouseDown={(e) => { e.preventDefault(); insertMention(d.name) }}
            >
              <span className="inline-flex h-5 flex-none items-center rounded-[5px] bg-human px-[7px] text-xs font-bold text-human-ink">{d.name}</span>
              <span className="max-w-[170px] truncate text-foreground-secondary">{d.text}</span>
              <span className="ml-auto text-xs text-muted-foreground">{t("slide", { n: review.slugs.indexOf(d.slide) + 1 })}</span>
            </div>
          ))}
        </div>
      )}
      <div className={`px-3 pb-2.5 text-xs text-muted-foreground ${reveal ? "review-reveal review-reveal-late" : ""}`}>{t("footer")}</div>
    </>
  )
}
