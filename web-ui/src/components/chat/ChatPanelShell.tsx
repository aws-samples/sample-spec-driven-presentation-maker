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
 */

"use client"

import { useRef, useEffect, useState, useCallback } from "react"
import { ChatPanel, ChatPanelHandle } from "@/components/chat/ChatPanel"
import { MessageSquare, PanelRightClose, SquarePen, Layers } from "lucide-react"
import { LocalOnly, IS_LOCAL } from "@/lib/mode"

export type ChatTabKey = "new" | "deck"


/** Model info for local ACP agent */
interface AcpModel { modelId: string; name: string; description?: string }

function ModelSelector() {
  const [model, setModelState] = useState<string>("")
  const [models, setModels] = useState<AcpModel[]>([])

  useEffect(() => {
    fetch("/api/agent/models").then(r => r.json()).then(data => {
      setModels(data.available || [])
      setModelState(data.current || "")
    }).catch(() => {})
  }, [])

  if (models.length === 0) return null

  return (
    <select
      value={model}
      onChange={async (e) => {
        const v = e.target.value
        setModelState(v)
        sessionStorage.setItem("sdpm-model", v)
        fetch("/api/agent/models", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ modelId: v }),
        }).catch(() => {})
      }}
      className="text-[11px] bg-transparent border border-border rounded px-1.5 py-0.5 text-foreground-muted hover:text-foreground focus:outline-none focus:ring-1 focus:ring-brand-teal max-w-[140px]"
    >
      {models.map(m => <option key={m.modelId} value={m.modelId}>{m.name}</option>)}
    </select>
  )
}

interface ChatPanelShellProps {
  open: boolean
  onClose: () => void
  chatTab: ChatTabKey
  onChatTabChange: (tab: ChatTabKey) => void
  deckId: string | null
  deckName: string | null
  chatSessionId?: string
  slidePreviewUrls?: (string | null)[]
  slideSlugs?: string[]
  onDeckCreated?: (deckId: string) => void
  onPreviewInvalidated?: () => void
  onWorkflowPhase?: (phase: string) => void
  chatRef?: React.RefObject<ChatPanelHandle | null>
  inline?: boolean
}

export function ChatPanelShell({
  open, onClose, chatTab, onChatTabChange,
  deckId, deckName, chatSessionId, slidePreviewUrls, slideSlugs, onDeckCreated, onPreviewInvalidated, onWorkflowPhase, chatRef: externalChatRef,
  inline = false,
}: ChatPanelShellProps) {
  const internalChatRef = useRef<ChatPanelHandle>(null)
  const chatRef = externalChatRef || internalChatRef
  const panelRef = useRef<HTMLElement>(null)

  // Start ACP agent early so model list is available immediately
  useEffect(() => {
    if (!IS_LOCAL) return
    fetch("/api/agent/models").catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
    if (chatTab === "new" || panelAOwnsCurrentDeck) {
      setPanelAKey((k) => k + 1)
      setPanelADeckId(null)
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

  // Tab label for Panel A
  const panelALabel = panelAOwnsCurrentDeck ? (deckName || "Deck") : "New"

  const chatContent = (
    <div className="flex-1 overflow-hidden relative">
      {/* Panel A: New / deck-created-from-new */}
      <div className={`h-full ${panelAVisible ? "" : "hidden"}`}>
        <ChatPanel
          key={`a-${panelAKey}`}
          ref={panelAVisible ? chatRef : undefined}
          deckId="new"
          deckName="New Deck"
          slidePreviewUrls={panelAOwnsCurrentDeck ? (slidePreviewUrls || []) : []}
          slideSlugs={panelAOwnsCurrentDeck ? (slideSlugs || []) : []}
          onDeckCreated={handlePanelADeckCreated}
          onPreviewInvalidated={onPreviewInvalidated}
          onWorkflowPhase={onWorkflowPhase}
        />
      </div>

      {/* Panel B: existing deck chat — key is stable, only bumped on external navigation */}
      {showPanelB && (
        <div className={`h-full ${panelBVisible ? "" : "hidden"}`}>
          <ChatPanel
            key={`b-${panelBKey}`}
            ref={panelBVisible ? chatRef : undefined}
            deckId={deckId!}
            deckName={deckName || undefined}
            chatSessionId={chatSessionId}
            slidePreviewUrls={slidePreviewUrls || []}
            slideSlugs={slideSlugs || []}
            onDeckCreated={handlePanelBDeckCreated}
            onPreviewInvalidated={onPreviewInvalidated}
            onWorkflowPhase={onWorkflowPhase}
          />
        </div>
      )}
    </div>
  )

  if (inline) {
    return <div className="h-full flex flex-col">{chatContent}</div>
  }

  return (
    <>
      {open && (
        <div
          className="sm:hidden fixed inset-0 z-40 bg-black/60"
          onClick={onClose}
        />
      )}

      <aside
        ref={panelRef}
        data-open={open}
        className="chat-panel fixed right-0 top-12 bottom-0 z-50 w-full sm:w-[400px] flex flex-col bg-background-panel pb-4"
        style={{
          boxShadow: open
            ? "-1px 0 0 var(--border), -20px 0 40px oklch(0 0 0 / 30%)"
            : "none",
        }}
      >
        {/* Header */}
        <div className="flex-none px-4 pt-3 pb-0">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-md flex items-center justify-center bg-brand-teal-soft">
                <MessageSquare className="h-2.5 w-2.5 text-brand-teal" />
              </div>
              <span className="text-[13px] font-semibold tracking-[-0.01em]">Chat</span>
              <LocalOnly><ModelSelector /></LocalOnly>
            </div>
            <div className="flex items-center gap-0.5">
              <button
                onClick={handleNewChat}
                title="New chat"
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-background-hover transition-all"
                aria-label="Start new chat"
              >
                <SquarePen className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-background-hover transition-all"
                aria-label="Close chat panel"
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
              className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg transition-all truncate max-w-[240px] ${
                panelAVisible
                  ? "text-foreground bg-white/[0.07]"
                  : "text-foreground-muted hover:text-foreground-secondary hover:bg-white/[0.03]"
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
                className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg transition-all truncate max-w-[240px] ${
                  panelBVisible
                    ? "text-foreground bg-white/[0.07]"
                    : "text-foreground-muted hover:text-foreground-secondary hover:bg-white/[0.03]"
                }`}
              >
                <Layers className="h-3 w-3 flex-none" />
                <span className="truncate">{deckName || "Deck"}</span>
              </button>
            )}
          </div>
        </div>

        <div className="mx-4 mt-3 border-t border-white/[0.06]" />

        {chatContent}
      </aside>
    </>
  )
}
