// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChatPanelShell — Persistent chat panel with up to two ChatPanels.
 *
 * Two ChatPanel instances:
 * - **Panel A** (mounted): Starts as "New". On create_deck, its tab label
 *   changes to the deck name. No remount, streaming continues.
 * - **Panel B** (mounted when existing deck is open): Shows the existing deck's chat.
 *   On create_deck from Panel B, navigates to new deck; Panel B is unmounted and
 *   Panel A shows the new deck context.
 *
 * create_deck from Panel A:
 *   - Tab label changes from "New" to deck name
 *   - If Panel B existed (old deck), it disappears
 *   - Screen navigates to new deck
 *
 * create_deck from Panel B:
 *   - Screen navigates to new deck
 *   - Panel B remounts with new deck's key
 *   - Panel A stays as-is
 *
 * Home screen layouts (the same element throughout, so Panel A keeps its state):
 * - **stage**: no deck open and Panel A blank — Panel A is the composer at the top of the home
 *   screen, above the deck list.
 * - **center**: Panel A has a conversation but no deck yet — the conversation fills the page.
 * - **sheet**: everywhere else — the chat sheet beside the page.
 * Moves between them animate real heights, widths and margins (lib/motion), so text reflows as it
 * moves: stage → center when the first message arrives, center → sheet when Panel A creates its
 * deck or the user goes back to the deck list (`onPark`; the conversation stays in the sheet).
 */

"use client"

import { useRef, useEffect, useLayoutEffect, useState, useCallback } from "react"
import { MORPH_EASE, MORPH_MS, canAnimate, isDesktop, revealHeight } from "@/lib/motion"
import { ChatPanel, ChatPanelHandle } from "@/components/chat/ChatPanel"
import { MessageSquare, PanelRightClose, SquarePen, Layers, ChevronLeft } from "lucide-react"
import { IS_LOCAL } from "@/lib/mode"
import { stopLocalAgent } from "@/services/localService"
import { notifyError } from "@/lib/errors"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { useTranslations } from "next-intl"
import type { SessionOrigin } from "@/lib/local/kiro-sessions.types"

export type ChatTabKey = "new" | "deck"
export type ChatLayout = "stage" | "center" | "sheet"

const CHAT_WIDTH_KEY = "sdpm-chat-width"
const DEFAULT_WIDTH = 440
const MIN_WIDTH = 360
const MAX_WIDTH_PX = 600
/** The centred column: its widest and its side padding (sm:px-10). */
const CENTER_MAX = 760
const CENTER_PAD = 40


interface ChatPanelShellProps {
  open: boolean
  onClose: () => void
  chatTab: ChatTabKey
  onChatTabChange: (tab: ChatTabKey) => void
  deckId: string | null
  deckName: string | null
  chatSessionId?: string
  sessionOrigin?: SessionOrigin
  onDeckCreated?: (deckId: string) => void
  onPreviewInvalidated?: () => void
  onWorkflowPhase?: (phase: string) => void
  onLoadingChange?: (isLoading: boolean) => void
  chatRef?: React.RefObject<ChatPanelHandle | null>
  inline?: boolean
  /** The home screen: Panel A may take the stage and the centre (no deck is open). */
  stageAllowed?: boolean
  /** Panel A's conversation was moved to the sheet; it stays there until a new chat. */
  parked?: boolean
  /** Move Panel A's conversation to the sheet (the user goes back to the deck list). */
  onPark?: () => void
  /** A new chat ends the parking. */
  onUnpark?: () => void
  /** Reports the layout (the page lays itself out around it). */
  onLayoutChange?: (layout: ChatLayout) => void
  /** Panel A got its first message: the chat counts as open from now on. */
  onStageExit?: () => void
}

export function ChatPanelShell({
  open, onClose, chatTab, onChatTabChange,
  deckId, deckName, chatSessionId, sessionOrigin, onDeckCreated, onPreviewInvalidated, onWorkflowPhase, onLoadingChange, chatRef: externalChatRef,
  inline = false, stageAllowed = false, parked = false, onPark, onUnpark, onLayoutChange, onStageExit,
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

  // Panel A is blank (no messages yet); set by the panel itself.
  const [panelABlank, setPanelABlank] = useState(true)
  const centered = stageAllowed && !inline && deckId === null && !parked
  const layout: ChatLayout = !centered ? "sheet" : panelABlank ? "stage" : "center"
  const staged = layout === "stage"
  const layoutRef = useRef(layout)
  const stageRectRef = useRef<DOMRect | null>(null)
  const exitRef = useRef({ onChatTabChange, onStageExit, onPark })
  exitRef.current = { onChatTabChange, onStageExit, onPark }
  const handlePanelABlank = useCallback((blank: boolean) => {
    if (!blank && layoutRef.current === "stage") {
      // Where the stage is now: the move to the centre starts from here.
      stageRectRef.current = panelRef.current?.getBoundingClientRect() ?? null
      exitRef.current.onChatTabChange("new")
      exitRef.current.onStageExit?.()
    } else if (!blank && layoutRef.current === "sheet") {
      // A conversation started in the sheet stays there.
      exitRef.current.onPark?.()
    }
    setPanelABlank(blank)
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
    } else if (prev === "center" && layout === "sheet" && isDesktop()) {
      morphCenterToSheet(aside, surfaceRef.current, sheetHeaderRef.current, panelWidth)
    }
    stageRectRef.current = null
  // panelWidth is read at the move only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, onLayoutChange])

  /** Close the panel on Escape (matches dialog conventions on mobile overlay). */
  useEffect(() => {
    if (!open || inline || layout !== "sheet") return
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, inline, layout, onClose])

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

  // When Panel A creates a deck, store the deckId so we know Panel A "owns" it
  const [panelADeckId, setPanelADeckId] = useState<string | null>(null)

  // Key for Panel A — bumped only by explicit "new chat" button
  const [panelAKey, setPanelAKey] = useState(0)

  // Key for Panel B — bumped when user opens a different deck externally
  const [panelBKey, setPanelBKey] = useState(0)

  // The deckId that Panel B was originally opened with
  const panelBOriginalDeckIdRef = useRef<string | null>(null)

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

  /** Panel A: create_deck → label changes, navigate to deck. No remount. */
  const handlePanelADeckCreated = useCallback((newDeckId: string) => {
    setPanelADeckId(newDeckId)
    onDeckCreated?.(newDeckId)
  }, [onDeckCreated])

  /** Panel B: create_deck → navigate to deck. Key stays same, no remount. */
  const panelBCreatedRef = useRef(false)
  const handlePanelBDeckCreated = useCallback((newDeckId: string) => {
    panelBCreatedRef.current = true
    onDeckCreated?.(newDeckId)
  }, [onDeckCreated])

  /** New chat button: reset Panel A to fresh state. */
  const handleNewChat = () => {
    if (IS_LOCAL) stopLocalAgent({ newChat: true }).catch((err) => notifyError(t("errorResetSession"), err))
    if (chatTab === "new" || panelAOwnsCurrentDeck) {
      setPanelAKey((k) => k + 1)
      setPanelADeckId(null)
      onUnpark?.()
    }
    onChatTabChange("new")
  }

  // When deckId changes externally (user clicks a different deck),
  // bump Panel B key so it remounts with new chat history.
  // But if Panel A or Panel B created this deck, don't bump.
  const prevDeckIdRef = useRef(deckId)

  useEffect(() => {
    if (deckId !== prevDeckIdRef.current) {
      if (deckId !== panelADeckId) {
        setPanelADeckId(null)
        if (panelBCreatedRef.current) {
          panelBCreatedRef.current = false
        } else {
          setPanelBKey((k) => k + 1)
          panelBOriginalDeckIdRef.current = deckId
        }
      }
      prevDeckIdRef.current = deckId
    }
  }, [deckId, panelADeckId])

  // Panel A "owns" the current deck if it created it
  const panelAOwnsCurrentDeck = panelADeckId !== null && panelADeckId === deckId

  // Show Panel B (existing deck chat) only when a deck is open AND Panel A didn't create it
  const showPanelB = deckId !== null && !panelAOwnsCurrentDeck

  // Determine which panel is visible
  // Panel A is visible when: tab is "new", OR Panel A owns a deck and tab is "deck",
  // OR Panel A just created a deck (panelADeckId set) but deckId hasn't caught up yet
  const panelAVisible = chatTab === "new" || (chatTab === "deck" && panelAOwnsCurrentDeck) || (chatTab === "deck" && panelADeckId !== null && !showPanelB)
  // Panel B is visible when: tab is "deck" and Panel A doesn't own the deck
  const panelBVisible = chatTab === "deck" && showPanelB
  // At the centre of the home screen Panel A is shown whatever the tab
  const panelAShown = panelAVisible || layout !== "sheet"

  // Tab label for Panel A
  const panelALabel = panelAOwnsCurrentDeck ? (deckName || t("deck")) : t("new")

  const chatContent = (
    <ErrorBoundary label="Chat">
      <div className={staged ? "relative" : "flex-1 min-h-0 overflow-hidden relative"}>
        {/* Panel A: New / deck-created-from-new (the stage and the centre on the home screen) */}
        <div className={staged ? "" : `h-full ${panelAShown ? "" : "hidden"}`}>
          <ChatPanel
            key={`a-${panelAKey}`}
            ref={panelAShown ? chatRef : undefined}
            deckId={panelADeckId ?? "new"}
            onDeckCreated={handlePanelADeckCreated}
            onPreviewInvalidated={onPreviewInvalidated}
            onWorkflowPhase={onWorkflowPhase}
            onLoadingChange={panelAShown ? onLoadingChange : undefined}
            visible={(open || layout !== "sheet") && panelAShown}
            centered={layout !== "sheet"}
            onBlankChange={handlePanelABlank}
          />
        </div>

        {/* Panel B: existing deck chat — key is stable, only bumped on external navigation */}
        {showPanelB && (
          <div className={`h-full ${panelBVisible ? "" : "hidden"}`}>
            <ChatPanel
              key={`b-${panelBKey}`}
              ref={panelBVisible ? chatRef : undefined}
              deckId={deckId!}
              chatSessionId={chatSessionId}
              sessionOrigin={sessionOrigin}
              onDeckCreated={handlePanelBDeckCreated}
              onPreviewInvalidated={onPreviewInvalidated}
              onWorkflowPhase={onWorkflowPhase}
              onLoadingChange={panelBVisible ? onLoadingChange : undefined}
            />
          </div>
        )}
      </div>
    </ErrorBoundary>
  )

  if (inline) {
    return <div className="h-full flex flex-col">{chatContent}</div>
  }

  return (
    <>
      {open && layout === "sheet" && (
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
        style={layout !== "sheet" ? undefined : { width: open ? panelWidth : 0 }}
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
          ref={surfaceRef}
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
          <div ref={centerBarRef} className="flex-none flex items-center justify-between pt-3">
            <button
              type="button"
              onClick={onPark}
              className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2 text-sm text-foreground-secondary motion-safe:transition-colors hover:bg-background-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              {t("toDecks")}
            </button>
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
        {layout === "sheet" && (<div ref={sheetHeaderRef} className="flex-none">
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
                onClick={handleNewChat}
                title={t("newChat")}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-background-hover transition-all"
                aria-label={t("startNewChat")}
              >
                <SquarePen className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-background-hover transition-all"
                aria-label={t("closePanel")}
              >
                <PanelRightClose className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Session tabs */}
          <div className="flex gap-1">
            {/* Panel A tab */}
            <button
              onClick={() => onChatTabChange(panelAOwnsCurrentDeck ? "deck" : "new")}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-all truncate max-w-[240px] ${
                panelAVisible
                  ? "text-foreground bg-foreground/[0.07]"
                  : "text-foreground-muted hover:text-foreground-secondary hover:bg-foreground/[0.03]"
              }`}
            >
              {panelAOwnsCurrentDeck ? (
                <Layers className="h-3 w-3 flex-none" />
              ) : (
                <SquarePen className="h-3 w-3 flex-none" />
              )}
              <span className="truncate">{panelALabel}</span>
            </button>

            {/* Panel B tab (existing deck) */}
            {showPanelB && (
              <button
                onClick={() => onChatTabChange("deck")}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-all truncate max-w-[240px] ${
                  panelBVisible
                    ? "text-foreground bg-foreground/[0.07]"
                    : "text-foreground-muted hover:text-foreground-secondary hover:bg-foreground/[0.03]"
                }`}
              >
                <Layers className="h-3 w-3 flex-none" />
                <span className="truncate">{deckName || t("deck")}</span>
              </button>
            )}
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
