// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Decks page — Orchestrator for list view and workspace view.
 *
 * Uses URL hash (#deckId) to switch between list and workspace without
 * requiring dynamic routes (compatible with Next.js static export).
 *
 * State management is delegated to custom hooks:
 * - useDeckList: deck list fetching, search, favorites, actions
 * - useWorkspace: active deck, polling, hash routing, chat state
 *
 * Rendering is delegated to:
 * - AppShell: header chrome
 * - DeckListView: deck list with search, tabs, card grid
 * - SlideCarousel + DeckActions: workspace slide preview
 * - ChatPanelShell: persistent right-side chat panel
 */

"use client"

import { useState, useRef, useCallback } from "react"
import { useAuth } from "react-oidc-context"
import { AppShell } from "@/components/AppShell"
import { DeckListView } from "@/components/deck/DeckListView"
import { SlideCarousel } from "@/components/deck/SlideCarousel"
import { DeckActions } from "@/components/deck/DeckActions"
import { DeleteDeckModal } from "@/components/deck/DeleteDeckModal"
import { ChatPanelShell } from "@/components/chat/ChatPanelShell"
import { ChatPanelHandle } from "@/components/chat/ChatPanel"
import { updateVisibility, shareDeck } from "@/services/deckService"
import { useIsMobile } from "@/hooks/UseMobile"
import { useSwipe } from "@/hooks/useSwipe"
import { useDeckList } from "@/hooks/useDeckList"
import { useWorkspace } from "@/hooks/useWorkspace"
import { Plus, MessageSquare, Image as ImageIcon, Star } from "lucide-react"

export default function DecksPage() {
  const auth = useAuth()
  const isMobile = useIsMobile()
  const idToken = auth.user?.id_token

  /* ── Workspace state (hash routing, deck polling, chat) ── */
  const ws = useWorkspace(idToken, auth.isAuthenticated)

  /* ── List state (decks, search, favorites, actions) ── */
  const list = useDeckList(idToken, auth.isAuthenticated, ws.activeDeckId)

  /* ── Local UI state ── */
  const [fabOpen, setFabOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<"chat" | "preview">("chat")
  const [workflowPhase, setWorkflowPhase] = useState<string | null>(null)
  const chatRef = useRef<ChatPanelHandle>(null)
  const swipeRef = useSwipe(
    () => setActiveTab("preview"),
    () => setActiveTab("chat"),
  )

  /** Handle inline style selection — insert message into chat input. */
  const handleStyleSelect = useCallback((name: string) => {
    const hasArtDirection = ws.deck?.specs?.artDirection != null
    const msg = hasArtDirection
      ? `I want to change the style to "${name}". `
      : `I'll use the "${name}" style. `
    chatRef.current?.insertAtCursor(msg)
  }, [ws.deck?.specs?.artDirection])

  /* ── Render ── */
  return (
    <AppShell
      deckName={ws.isWorkspace && ws.deck ? ws.deck.name : undefined}
      onBack={ws.isWorkspace ? ws.navigateToList : undefined}
      chatOpen={ws.chatOpen}
      onChatToggle={() => ws.setChatOpen((prev) => !prev)}
    >
      <div className="flex-1 overflow-hidden relative">
        <main className={`h-full overflow-y-auto transition-[margin] duration-350 ease-[cubic-bezier(.4,0,.6,1)] ${ws.chatOpen ? "sm:mr-[400px]" : ""}`}>
          {ws.isWorkspace ? (
            <>
              {/* Mobile tab bar */}
              {ws.canChat && isMobile && (
                <div className="flex border-b border-border">
                  <button
                    onClick={() => setActiveTab("chat")}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-3 text-xs font-medium transition-colors ${
                      activeTab === "chat" ? "text-foreground border-b-2 border-foreground" : "text-foreground-muted"
                    }`}
                  >
                    <MessageSquare className="h-4 w-4" />
                    Chat
                  </button>
                  <button
                    onClick={() => setActiveTab("preview")}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-3 text-xs font-medium transition-colors ${
                      activeTab === "preview" ? "text-foreground border-b-2 border-foreground" : "text-foreground-muted"
                    }`}
                  >
                    <ImageIcon className="h-4 w-4" />
                    Preview
                    {ws.hasSlides && <span className="w-1.5 h-1.5 rounded-full bg-green-500" />}
                  </button>
                </div>
              )}

              {/* Workspace: slide preview */}
              <div ref={isMobile ? swipeRef : undefined} className="h-full">
                {isMobile && ws.canChat && activeTab === "chat" ? (
                  /* Mobile chat tab — ChatPanelShell renders inline on mobile */
                  <ChatPanelShell
                    open={true}
                    onClose={() => setActiveTab("preview")}
                    chatTab={ws.chatTab}
                    onChatTabChange={ws.setChatTab}
                    chatRef={chatRef}
                    deckId={ws.isWorkspace && !ws.isNew ? ws.activeDeckId : null}
                    deckName={ws.deck?.name || null}
                    chatSessionId={ws.deck?.chatSessionId}
                    slidePreviewUrls={ws.deck?.slides.map(s => s.previewUrl) || []}
                    onDeckCreated={ws.handleDeckCreated} onPreviewInvalidated={() => ws.setPptxRequested(true)}
                    onWorkflowPhase={setWorkflowPhase}
                    inline
                  />
                ) : (
                  <SlideCarousel
                    slides={ws.deck?.slides || []}
                    defsUrl={ws.deck?.defsUrl}
                    deckId={ws.isNew ? ws.createdDeckId || undefined : ws.activeDeckId!}
                    deckName={ws.deck?.name}
                    pptxUrl={ws.deck?.pptxUrl}
                    isLoading={ws.waitingForPng || false}
                    scrollToSlide={ws.scrollToSlide}
                    onScrollComplete={() => ws.setScrollToSlide("")}
                    specs={ws.deck?.specs}
                    workflowPhase={workflowPhase}
                    onStyleSelect={handleStyleSelect}
                    idToken={idToken}
                    onSlideClick={(page) => {
                      const dName = ws.deck?.name || "Deck"
                      const mention = ws.activeDeckId
                        ? `@${dName}(#${ws.activeDeckId}):Page ${page} `
                        : `@Page ${page} `
                      const insert = () => chatRef.current?.insertAtCursor(mention)
                      if (ws.chatOpen) {
                        insert()
                      } else {
                        ws.setChatTab("deck")
                        ws.setChatOpen(true)
                        setTimeout(insert, 400)
                      }
                    }}
                    ownerAlias={!ws.isOwner ? ws.deck?.ownerAlias : undefined}
                    headerActions={
                      ws.activeDeckId && !ws.isNew ? (
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => list.handleToggleFavorite(ws.activeDeckId!, list.favoriteIds.has(ws.activeDeckId!) ? "remove" : "add")}
                            className={`p-1.5 rounded-md transition-colors ${
                              list.favoriteIds.has(ws.activeDeckId!)
                                ? "text-brand-amber"
                                : "text-foreground-muted hover:text-brand-amber"
                            }`}
                            aria-label={list.favoriteIds.has(ws.activeDeckId!) ? "Remove from favorites" : "Add to favorites"}
                          >
                            <Star className={`h-4 w-4 ${list.favoriteIds.has(ws.activeDeckId!) ? "fill-current" : ""}`} />
                          </button>
                          {ws.isOwner && (
                            <DeckActions
                              visibility={ws.deck?.visibility}
                              onVisibilityChange={async (v) => {
                                if (!idToken || !ws.activeDeckId || !ws.deck) return
                                await updateVisibility(ws.activeDeckId, v, idToken)
                                ws.setDeck({ ...ws.deck, visibility: v })
                              }}
                              onShare={async (sub, action, alias) => {
                                if (!idToken || !ws.activeDeckId) return { collaborators: [], collaboratorAliases: {} }
                                const result = await shareDeck(ws.activeDeckId, sub, idToken, action, alias)
                                if (ws.deck) ws.setDeck({ ...ws.deck, collaborators: result.collaborators, collaboratorAliases: result.collaboratorAliases })
                                return result
                              }}
                              idToken={idToken}
                              collaborators={ws.deck?.collaborators}
                              collaboratorAliases={ws.deck?.collaboratorAliases}
                            />
                          )}
                        </div>
                      ) : undefined
                    }
                  />
                )}
              </div>
            </>
          ) : (
            <>
              <DeckListView
                decks={list.tabDecks}
                activeTab={list.activeListTab}
                onTabChange={(tab) => list.setActiveListTab(tab as typeof list.activeListTab)}
                searchQuery={list.searchQuery}
                onSearchChange={list.setSearchQuery}
                searchResults={list.searchResults}
                searching={list.searching}
                onDeckOpen={ws.openDeck}
                onNewDeck={() => { ws.setChatOpen(true); ws.setChatTab("new") }}
                favoriteIds={list.favoriteIds}
                onToggleFavorite={list.handleToggleFavorite}
                onDelete={list.handleDelete}
                onToggleVisibility={list.handleToggleVisibility}
                onDownload={list.handleDownload}
                loading={list.loading}
              />
              {list.error && (
                <div className="max-w-5xl mx-auto px-5 sm:px-8">
                  <div className="text-[12px] text-red-400 bg-red-500/10 rounded-lg px-4 py-3 mb-6 border border-red-500/20">
                    {list.error}
                  </div>
                </div>
              )}
            </>
          )}
        </main>

        {/* Chat Panel (persistent, desktop) — hidden on mobile workspace chat tab */}
        <div className={isMobile && ws.isWorkspace && ws.canChat && activeTab === "chat" ? "hidden" : ""}>
          <ChatPanelShell
            open={ws.chatOpen}
            onClose={() => ws.setChatOpen(false)}
            chatTab={ws.chatTab}
            onChatTabChange={ws.setChatTab}
            chatRef={chatRef}
            deckId={ws.isWorkspace && !ws.isNew ? ws.activeDeckId : null}
            deckName={ws.deck?.name || null}
            chatSessionId={ws.deck?.chatSessionId}
            slidePreviewUrls={ws.deck?.slides.map(s => s.previewUrl) || []}
            onDeckCreated={ws.handleDeckCreated} onPreviewInvalidated={() => ws.setPptxRequested(true)}
            onWorkflowPhase={setWorkflowPhase}
          />
        </div>
      </div>

      {list.deleteTarget && (
        <DeleteDeckModal
          deckName={list.deleteTarget.name}
          onConfirm={list.confirmDelete}
          onCancel={() => list.setDeleteTarget(null)}
        />
      )}

      {isMobile && !ws.isWorkspace && (
        <div className="fixed right-4 z-40" style={{ bottom: "calc(1.5rem + env(safe-area-inset-bottom, 0px))" }}>
          {fabOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setFabOpen(false)} />
              <div className="absolute bottom-16 right-0 z-40 flex flex-col gap-2 items-end">
                <button
                  onClick={() => { setFabOpen(false); ws.setChatOpen(true); ws.setChatTab("new") }}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-full bg-brand-teal text-primary-foreground shadow-lg text-sm font-medium animate-card-in"
                >
                  <Plus className="h-4 w-4" />
                  New Deck
                </button>
              </div>
            </>
          )}
          <button
            onClick={() => setFabOpen(!fabOpen)}
            className={`w-14 h-14 rounded-full bg-brand-teal text-primary-foreground shadow-xl flex items-center justify-center transition-transform duration-200 ${fabOpen ? "rotate-45" : ""}`}
            aria-label="Create new deck"
            aria-expanded={fabOpen}
          >
            <Plus className="h-6 w-6" />
          </button>
        </div>
      )}

    </AppShell>
  )
}
