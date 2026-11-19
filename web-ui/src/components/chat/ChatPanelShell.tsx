// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanelShell — the persistent chat: one conversation per screen.
 *
 * - **Home conversation**: the chat of the home screen (no deck open). It stays when the user
 *   opens a deck or goes back to the list, hidden but still streaming, and only "New chat"
 *   clears it. When it creates a deck it becomes that deck's chat (same instance, so the stream
 *   goes on) and the home screen gets a blank conversation.
 * - **Deck conversation**: the chat of the open deck, mounted while the deck is open. A deck
 *   created from it keeps the same instance.
 *
 * Home screen layouts (the same element throughout, so the home conversation keeps its state):
 * - **stage**: the home conversation is blank — it is the composer at the top of the home
 *   screen, above the deck list.
 * - **center**: the home conversation has messages — it fills the first screenful and the deck
 *   list follows below it.
 * - **sheet**: a deck is open — the chat sheet beside the page.
 * Moves between them animate real heights, widths and margins (lib/motion), so text reflows as it
 * moves: stage → center when the first message arrives, center → sheet when the home
 * conversation creates its deck.
 */

"use client"

import { useRef, useEffect, useLayoutEffect, useState, useCallback } from "react"
import { MORPH_EASE, MORPH_MS, canAnimate, isDesktop, revealHeight } from "@/lib/motion"
import { ChatPanel, ChatPanelHandle } from "@/components/chat/ChatPanel"
import { MessageSquare, PanelRightClose, SquarePen } from "lucide-react"
import { IS_LOCAL } from "@/lib/mode"
import { stopLocalAgent } from "@/services/localService"
import { notifyError } from "@/lib/errors"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { useTranslations } from "next-intl"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"

export type ChatLayout = "stage" | "center" | "sheet"

const CHAT_WIDTH_KEY = "sdpm-chat-width"
const DEFAULT_WIDTH = 440
const MIN_WIDTH = 360
const MAX_WIDTH_PX = 600
/** The centred column: its widest and its side padding (sm:px-10). */
const CENTER_MAX = 760
const CENTER_PAD = 40


/** The open deck's conversation. `fromHome`: it began as the home conversation (no linked session to load). */
interface DeckChat {
  key: string
  deckId: string
  fromHome: boolean
}

interface ChatPanelShellProps {
  open: boolean
  onClose: () => void
  deckId: string | null
  chatSessionId?: string
  sessionOrigin?: SessionOrigin
  onDeckCreated?: (deckId: string) => void
  onPreviewInvalidated?: () => void
  onWorkflowPhase?: (phase: string) => void
  onLoadingChange?: (isLoading: boolean) => void
  chatRef?: React.RefObject<ChatPanelHandle | null>
  /**
   * Phone deck screen, chat tab: the sheet fills the screen below this y (the page's chat/preview
   * tab bar), without its own header or backdrop. The shell stays the same instance on every
   * screen, so no conversation is lost when the phone switches between list, deck and tabs.
   */
  phoneTop?: number
  /** Swipe handling for the phone chat tab (swipe left to the preview). */
  swipeRef?: React.RefObject<HTMLDivElement | null>
  /** The home screen: the home conversation may take the stage and the centre (no deck is open). */
  stageAllowed?: boolean
  /** Reports the layout (the page lays itself out around it). */
  onLayoutChange?: (layout: ChatLayout) => void
  /** The home conversation got its first message: the chat counts as open from now on. */
  onStageExit?: () => void
}

export function ChatPanelShell({
  open, onClose,
  deckId, chatSessionId, sessionOrigin, onDeckCreated, onPreviewInvalidated, onWorkflowPhase, onLoadingChange, chatRef: externalChatRef,
  phoneTop, swipeRef, stageAllowed = false, onLayoutChange, onStageExit,
}: ChatPanelShellProps) {
  const t = useTranslations("chatShell")
  const internalChatRef = useRef<ChatPanelHandle>(null)
  const chatRef = externalChatRef || internalChatRef
  const panelRef = useRef<HTMLElement>(null)

  // Resize state
  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH)
  const resizingRef = useRef(false)

  /** Restore saved width from localStorage after mount. */
  useEffect(() => {
    const saved = localStorage.getItem(CHAT_WIDTH_KEY)
    if (saved) setPanelWidth(Math.max(MIN_WIDTH, Math.min(Number(saved), MAX_WIDTH_PX)))
  }, [])

  // The home conversation and, while a deck is open, that deck's conversation. Keys only change
  // when a conversation is replaced, so a stream never restarts by itself.
  const [homeKey, setHomeKey] = useState(0)
  const [deckChat, setDeckChat] = useState<DeckChat | null>(() => (deckId ? { key: `deck:${deckId}`, deckId, fromHome: false } : null))
  // A deck a conversation has just created, until `deckId` (the page's hash) catches up.
  const [pendingDeckId, setPendingDeckId] = useState<string | null>(null)
  // Opening another deck (or the list) swaps the deck conversation, adjusted during render so
  // the old one never shows under the new deck.
  const [seenDeckId, setSeenDeckId] = useState(deckId)
  if (deckId !== seenDeckId) {
    setSeenDeckId(deckId)
    setPendingDeckId(null)
    setDeckChat((cur) => (deckId === null ? null : cur?.deckId === deckId ? cur : { key: `deck:${deckId}`, deckId, fromHome: false }))
  }
  const shownDeckChat = deckChat && (deckChat.deckId === deckId || deckChat.deckId === pendingDeckId) ? deckChat : null

  // The home conversation is blank (no messages yet); set by the panel itself.
  const [homeBlank, setHomeBlank] = useState(true)
  const phoneTab = phoneTop !== undefined
  const centered = stageAllowed && !phoneTab && deckId === null
  const layout: ChatLayout = !centered ? "sheet" : homeBlank && !shownDeckChat ? "stage" : "center"
  const staged = layout === "stage"
  const layoutRef = useRef(layout)
  const stageRectRef = useRef<DOMRect | null>(null)
  const exitRef = useRef({ onStageExit })
  exitRef.current = { onStageExit }
  const handleHomeBlank = useCallback((blank: boolean) => {
    if (!blank && layoutRef.current === "stage") {
      // Where the stage is now: the move to the centre starts from here.
      stageRectRef.current = panelRef.current?.getBoundingClientRect() ?? null
      exitRef.current.onStageExit?.()
    }
    setHomeBlank(blank)
  }, [])

  const centerBarRef = useRef<HTMLDivElement>(null)
  const sheetHeaderRef = useRef<HTMLDivElement>(null)
  const surfaceRef = useRef<HTMLDivElement>(null)
  const prevLayoutRef = useRef(layout)
  useLayoutEffect(() => {
    const prev = prevLayoutRef.current
    prevLayoutRef.current = layout
    layoutRef.current = layout
    onLayoutChange?.(layout)
    const aside = panelRef.current
    if (prev === layout || !canAnimate(aside)) return
    if (prev === "stage" && layout === "center") {
      morphStageToCenter(aside, stageRectRef.current)
      if (centerBarRef.current) revealHeight(centerBarRef.current)
    } else if (prev === "center" && layout === "sheet") {
      // The deck list may have been scrolled into view below the conversation.
      if (aside.parentElement) aside.parentElement.scrollTop = 0
      if (isDesktop()) morphCenterToSheet(aside, surfaceRef.current, sheetHeaderRef.current, panelWidth)
    }
    stageRectRef.current = null
  // panelWidth is read at the move only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, onLayoutChange])

  /** Close the panel on Escape (matches dialog conventions on mobile overlay). */
  useEffect(() => {
    if (!open || phoneTab || layout !== "sheet") return
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, phoneTab, layout, onClose])

  /** Apply width to panel DOM without React re-render. */
  const applyWidth = useCallback((w: number) => {
    const el = panelRef.current
    if (el) el.style.width = `${w}px`
  }, [])

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    resizingRef.current = true
    const startX = e.clientX
    const startW = panelWidth
    const maxW = Math.min(MAX_WIDTH_PX, window.innerWidth * 0.5)

    panelRef.current?.classList.add("is-resizing")

    const onMove = (ev: MouseEvent) => {
      applyWidth(Math.max(MIN_WIDTH, Math.min(startW + (startX - ev.clientX), maxW)))
    }
    const onUp = (ev: MouseEvent) => {
      resizingRef.current = false
      document.removeEventListener("mousemove", onMove)
      document.removeEventListener("mouseup", onUp)
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      panelRef.current?.classList.remove("is-resizing")
      const finalW = Math.max(MIN_WIDTH, Math.min(startW + (startX - ev.clientX), maxW))
      localStorage.setItem(CHAT_WIDTH_KEY, String(finalW))
      setPanelWidth(finalW)
    }
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
    document.addEventListener("mousemove", onMove)
    document.addEventListener("mouseup", onUp)
  }, [panelWidth, applyWidth])

  // Focus textarea when panel opens
  useEffect(() => {
    if (open) {
      const timer = setTimeout(() => {
        const ta = panelRef.current?.querySelector("textarea")
        ta?.focus()
      }, 360)
      return () => clearTimeout(timer)
    }
  }, [open])

  /** The home conversation created a deck: it becomes that deck's chat; home starts blank. */
  const handleHomeDeckCreated = useCallback((newDeckId: string) => {
    setDeckChat({ key: `home:${homeKey}`, deckId: newDeckId, fromHome: true })
    setPendingDeckId(newDeckId)
    setHomeKey((k) => k + 1)
    setHomeBlank(true)
    onDeckCreated?.(newDeckId)
  }, [homeKey, onDeckCreated])

  /** The deck conversation created another deck: it follows, same instance. */
  const handleDeckChatCreated = useCallback((newDeckId: string) => {
    setDeckChat((cur) => (cur ? { ...cur, deckId: newDeckId } : cur))
    setPendingDeckId(newDeckId)
    onDeckCreated?.(newDeckId)
  }, [onDeckCreated])

  /** New chat (home only): clear the home conversation. */
  const handleNewChat = () => {
    if (IS_LOCAL) stopLocalAgent({ newChat: true }).catch((err) => notifyError(t("errorResetSession"), err))
    setHomeKey((k) => k + 1)
    setHomeBlank(true)
  }

  const homeShown = shownDeckChat === null
  const panelVisible = open || layout !== "sheet"

  const chatContent = (
    <ErrorBoundary label="Chat">
      <div className={staged ? "relative" : "flex-1 min-h-0 overflow-hidden relative"}>
        {/* The deck conversation comes first, so a home conversation that becomes it keeps its place. */}
        {deckChat && (
          <div key={deckChat.key} className={shownDeckChat ? "h-full" : "hidden"}>
            <ChatPanel
              ref={shownDeckChat ? chatRef : undefined}
              deckId={deckChat.deckId}
              chatSessionId={deckChat.fromHome ? undefined : chatSessionId}
              sessionOrigin={deckChat.fromHome ? undefined : sessionOrigin}
              onDeckCreated={handleDeckChatCreated}
              onPreviewInvalidated={onPreviewInvalidated}
              onWorkflowPhase={onWorkflowPhase}
              onLoadingChange={shownDeckChat ? onLoadingChange : undefined}
              centered={!!shownDeckChat && layout !== "sheet"}
            />
          </div>
        )}
        <div key={`home:${homeKey}`} className={homeShown ? (staged ? "" : "h-full") : "hidden"}>
          <ChatPanel
            ref={homeShown ? chatRef : undefined}
            deckId="new"
            onDeckCreated={handleHomeDeckCreated}
            onPreviewInvalidated={onPreviewInvalidated}
            onWorkflowPhase={onWorkflowPhase}
            onLoadingChange={homeShown ? onLoadingChange : undefined}
            visible={panelVisible && homeShown}
            centered={homeShown && layout !== "sheet"}
            onBlankChange={handleHomeBlank}
          />
        </div>
      </div>
    </ErrorBoundary>
  )

  return (
    <>
      {open && layout === "sheet" && !phoneTab && (
        <div
          className="sm:hidden fixed inset-0 z-40 bg-black/60"
          onClick={onClose}
        />
      )}

      <aside
        ref={panelRef}
        data-open={open}
        data-stage={staged ? "" : undefined}
        data-layout={layout}
        className={layout === "stage"
          ? "chat-stage relative order-first w-full flex-none px-5 sm:px-10"
          : layout === "center"
            ? "chat-stage relative order-first w-full h-full flex-none px-5 sm:px-10"
            : "chat-panel fixed right-0 top-12 bottom-0 z-50 w-full sm:relative sm:right-auto sm:top-auto sm:bottom-auto sm:z-auto sm:h-full sm:flex-none"}
        style={layout !== "sheet" ? undefined : phoneTab ? { top: phoneTop } : { width: open ? panelWidth : 0 }}
      >
        {/* Resize handle — absolute, left:-6px, outside inner overflow:hidden */}
        {layout === "sheet" && (
        <div
          className="chat-resize-handle hidden sm:flex"
          onMouseDown={handleResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label={t("resizePanel")}
        />
        )}
        {/* Inner — overflow:hidden clips during close, min-width prevents text reflow */}
        <div
          ref={(el) => {
            surfaceRef.current = el
            if (swipeRef) swipeRef.current = el
          }}
          data-chat-surface=""
          className={layout === "stage"
            ? "mx-auto flex w-full max-w-[760px] flex-col"
            : layout === "center"
              ? "chat-surface-center mx-auto flex h-full w-full max-w-[760px] flex-col pb-4"
              : "chat-panel-inner h-full flex flex-col bg-background-panel pb-4"}
          style={layout !== "sheet" ? undefined : {
            "--chat-panel-inner-w": `${panelWidth}px`,
            boxShadow: open
              ? "-1px 0 0 var(--border), -20px 0 40px oklch(0 0 0 / 30%)"
              : "none",
          } as React.CSSProperties}
        >
        {layout === "center" && (
          <div ref={centerBarRef} className="flex-none flex items-center justify-end pt-3">
            <button
              type="button"
              onClick={handleNewChat}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-sm text-foreground-secondary motion-safe:transition-colors hover:bg-background-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
            >
              <SquarePen className="h-3.5 w-3.5" aria-hidden="true" />
              {t("newChat")}
            </button>
          </div>
        )}
        {layout === "sheet" && !phoneTab && (<div ref={sheetHeaderRef} className="flex-none">
        {/* Header */}
        <div className="flex-none px-4 pt-3 pb-0">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-md flex items-center justify-center bg-brand-teal-soft">
                <MessageSquare className="h-2.5 w-2.5 text-brand-teal" />
              </div>
              <span className="text-sm font-semibold tracking-[-0.01em]">{t("chat")}</span>
            </div>
            <div className="flex items-center gap-0.5">
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-background-hover transition-all"
                aria-label={t("closePanel")}
              >
                <PanelRightClose className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="mx-4 mt-3 border-t border-border" />
        </div>)}

        {chatContent}
        </div>{/* end chat-panel-inner */}
      </aside>
    </>
  )
}

/**
 * The first message: the composer block grows from where the stage was to the whole page,
 * pushing the deck list down; the panel folds its heading and suggestions away meanwhile.
 */
function morphStageToCenter(aside: HTMLElement, from: DOMRect | null) {
  const container = aside.parentElement
  if (!from || !container) return
  // Where the user saw it; the page scrolls back to the top under the move.
  const top = from.top - container.getBoundingClientRect().top
  container.scrollTop = 0
  aside.animate(
    [
      { height: `${from.height}px`, transform: `translateY(${top}px)` },
      { height: `${container.clientHeight}px`, transform: "translateY(0)" },
    ],
    { duration: MORPH_MS, easing: MORPH_EASE },
  )
}

/**
 * The deck exists (or the user went back to the list): the centred column slides right and
 * narrows into the sheet, while the page opens on its left. Widths and margins move, not
 * pictures, so the conversation rewraps as it goes.
 */
function morphCenterToSheet(aside: HTMLElement, surface: HTMLElement | null, header: HTMLElement | null, toWidth: number) {
  const container = aside.parentElement
  if (!container || !surface) return
  const fromWidth = container.clientWidth
  const fromInner = Math.min(CENTER_MAX, fromWidth - 2 * CENTER_PAD)
  const side = (fromWidth - fromInner) / 2
  const timing = { duration: MORPH_MS, easing: MORPH_EASE }
  aside.classList.add("is-morphing")
  const move = aside.animate([{ width: `${fromWidth}px` }, { width: `${toWidth}px` }], timing)
  surface.animate(
    [
      { marginLeft: `${side}px`, marginRight: `${side}px`, marginTop: "0px", marginBottom: "0px" },
      { marginLeft: "8px", marginRight: "8px", marginTop: "8px", marginBottom: "8px" },
    ],
    timing,
  )
  if (header) revealHeight(header, timing.duration)
  move.finished.finally(() => aside.classList.remove("is-morphing")).catch(() => {})
}
