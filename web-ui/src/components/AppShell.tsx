// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AppShell — Top-level layout with minimal frosted-glass header (48px).
 *
 * Provides the structural shell for all pages:
 * - Header: Logo/back-nav (left), avatar + chat toggle (right)
 * - Content area: flex container that accommodates main content + chat panel
 *
 * The chat panel margin transition is handled by the parent page via
 * the `chatOpen` prop, which controls `margin-right` on the main content.
 *
 * @param props.children - Main page content
 * @param props.deckName - When set, header shows ← back nav with deck name
 * @param props.onBack - Callback to navigate back to deck list
 * @param props.chatOpen - Whether the chat panel is currently open
 * @param props.onChatToggle - Callback to toggle chat panel visibility
 * @returns App shell with header and content area
 */

"use client"

import { ReactNode, useState, useRef, useEffect } from "react"
import { useAuth } from "@/hooks/useAuth"
import { usePreferences } from "@/hooks/usePreferences"
import { Layers, ChevronLeft, MessageSquare } from "lucide-react"

interface AppShellProps {
  children: ReactNode
  deckName?: string
  onBack?: () => void
  chatOpen?: boolean
  onChatToggle?: () => void
}

export function AppShell({ children, deckName, onBack, chatOpen = false, onChatToggle }: AppShellProps) {
  const { user } = useAuth()
  const alias = user?.profile?.preferred_username || user?.profile?.email?.split("@")[0] || ""
  const initials = alias ? alias.slice(0, 2).toLowerCase() : ""
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const { sendWithEnter, setSendWithEnter } = usePreferences()

  // Close menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    if (menuOpen) document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen])

  return (
    <div className="flex flex-col h-screen relative z-10">
      {/* ── Header ── */}
      <header
        className="header-glass safe-top flex-none flex items-center justify-between px-5 h-12 border-b border-border"
        role="banner"
      >
        <nav className="flex items-center gap-2.5" aria-label="Main navigation">
          {deckName && onBack ? (
            <button
              onClick={onBack}
              className="flex items-center gap-2 text-foreground-secondary hover:text-foreground transition-colors"
              aria-label="Back to decks"
            >
              <ChevronLeft className="h-4 w-4" />
              <span className="text-sm font-semibold tracking-[-0.02em] truncate max-w-[200px]">
                {deckName}
              </span>
            </button>
          ) : (
            <a href="/decks/" className="flex items-center gap-2.5 no-underline">
              <div className="w-6 h-6 rounded-md flex items-center justify-center bg-brand-teal-soft">
                <Layers className="h-3 w-3 text-brand-teal" />
              </div>
              <span className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                spec-driven-presentation-maker
              </span>
            </a>
          )}
        </nav>

        <div className="flex items-center gap-1">
          {initials && (
            <div ref={menuRef} className="relative">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-medium border border-border bg-card text-foreground-secondary hover:border-foreground/20 transition-colors"
              >
                {initials}
              </button>
              {menuOpen && (
                <div
                  className="absolute right-0 top-full mt-1.5 w-52 rounded-xl py-1.5 z-[60] border border-white/[0.08] shadow-[0_8px_32px_oklch(0_0_0/50%)]"
                  style={{ background: "oklch(0.14 0.005 260 / 95%)", backdropFilter: "blur(16px)" }}
                >
                  <div className="px-3.5 py-2 text-[11px] text-foreground/40 font-medium">{alias}</div>
                  <div className="my-1 border-t border-white/[0.06]" />
                  <button
                    onClick={() => setSendWithEnter(!sendWithEnter)}
                    className="w-full flex items-center justify-between px-3.5 py-2 text-[12px] font-medium text-foreground/70 hover:bg-white/[0.06] rounded-lg transition-colors"
                  >
                    <span>Send with Enter</span>
                    <span className={`w-8 h-[18px] rounded-full flex items-center px-0.5 transition-colors ${sendWithEnter ? "bg-brand-teal justify-end" : "bg-white/10 justify-start"}`}>
                      <span className="w-3.5 h-3.5 rounded-full bg-white shadow-sm" />
                    </span>
                  </button>
                </div>
              )}
            </div>
          )}
          {onChatToggle && (
            <button
              onClick={onChatToggle}
              className={`ml-1 w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-background-hover ${
                chatOpen ? "text-brand-teal" : "text-foreground-muted chat-toggle-pulse"
              }`}
              aria-label={chatOpen ? "Close chat" : "Open chat"}
              aria-expanded={chatOpen}
            >
              <MessageSquare className="h-4 w-4" />
            </button>
          )}
        </div>
      </header>

      {/* ── Content area ── */}
      {children}
    </div>
  )
}
