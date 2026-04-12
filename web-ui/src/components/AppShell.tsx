// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AppShell — Top-level layout with minimal frosted-glass header (48px).
 *
 * Provides the structural shell for all pages:
 * - Header: Logo/back-nav (left), chat toggle + user menu (right)
 * - Content area: flex container that accommodates main content + chat panel
 *
 * @param props.children - Main page content
 * @param props.deckName - When set, header shows ← back nav with deck name
 * @param props.onBack - Callback to navigate back to deck list
 * @param props.chatOpen - Whether the chat panel is currently open
 * @param props.onChatToggle - Callback to toggle chat panel visibility
 * @returns App shell with header and content area
 */

"use client"

import { ReactNode, useState, useRef, useEffect, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { usePreferences } from "@/hooks/usePreferences"
import { Layers, ChevronLeft, MessageSquare, CircleUser, LogOut } from "lucide-react"

interface AppShellProps {
  children: ReactNode
  deckName?: string
  onBack?: () => void
  chatOpen?: boolean
  onChatToggle?: () => void
}

export function AppShell({ children, deckName, onBack, chatOpen = false, onChatToggle }: AppShellProps) {
  const { user, signOut } = useAuth()
  const alias = user?.profile?.preferred_username || user?.profile?.email?.split("@")[0] || ""
  const email = user?.profile?.email || ""
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuVisible, setMenuVisible] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const itemsRef = useRef<(HTMLButtonElement | null)[]>([])
  const { sendWithEnter, setSendWithEnter } = usePreferences()

  // Chat pulse: show only until first click
  const [chatSeen, setChatSeen] = useState(true)
  useEffect(() => {
    setChatSeen(localStorage.getItem("sdpm-chat-seen") === "1")
  }, [])
  const handleChatToggle = useCallback(() => {
    if (!chatSeen) {
      localStorage.setItem("sdpm-chat-seen", "1")
      setChatSeen(true)
    }
    onChatToggle?.()
  }, [chatSeen, onChatToggle])

  // Menu open/close with animation
  const openMenu = useCallback(() => {
    setMenuOpen(true)
    requestAnimationFrame(() => setMenuVisible(true))
  }, [])
  const closeMenu = useCallback(() => {
    setMenuVisible(false)
    setTimeout(() => setMenuOpen(false), 150)
  }, [])
  const toggleMenu = useCallback(() => {
    menuOpen ? closeMenu() : openMenu()
  }, [menuOpen, closeMenu, openMenu])

  // Close on outside click
  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) closeMenu()
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen, closeMenu])

  // Keyboard navigation
  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        closeMenu()
        triggerRef.current?.focus()
        return
      }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault()
        const items = itemsRef.current.filter(Boolean) as HTMLButtonElement[]
        const idx = items.indexOf(document.activeElement as HTMLButtonElement)
        const next = e.key === "ArrowDown"
          ? (idx + 1) % items.length
          : (idx - 1 + items.length) % items.length
        items[next]?.focus()
      }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [menuOpen, closeMenu])

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

        <div className="flex items-center gap-1.5">
          {/* ── Chat toggle ── */}
          {onChatToggle && (
            <button
              onClick={handleChatToggle}
              className={`w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200 ${
                chatOpen
                  ? "text-brand-teal bg-brand-teal-soft"
                  : `text-foreground-secondary hover:bg-background-hover hover:text-foreground ${!chatSeen ? "chat-toggle-pulse" : ""}`
              }`}
              aria-label={chatOpen ? "Close chat" : "Open chat"}
              aria-expanded={chatOpen}
            >
              <MessageSquare className="h-4 w-4" />
            </button>
          )}

          {/* ── User menu ── */}
          <div ref={menuRef} className="relative">
            <button
              ref={triggerRef}
              onClick={toggleMenu}
              className={`w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200 ${
                menuOpen
                  ? "bg-brand-teal-soft text-brand-teal"
                  : "text-foreground-secondary hover:bg-background-hover hover:text-foreground"
              }`}
              aria-label="User menu"
              aria-expanded={menuOpen}
              aria-haspopup="true"
            >
              <CircleUser className="h-4 w-4" />
            </button>

            {menuOpen && (
              <div
                role="menu"
                aria-label="User menu"
                className={`absolute right-0 top-full mt-1.5 w-56 rounded-xl py-1.5 z-[60] border border-white/[0.08] shadow-[0_8px_32px_oklch(0_0_0/50%)] user-menu-enter ${menuVisible ? "user-menu-visible" : ""}`}
                style={{ background: "oklch(0.14 0.005 260 / 95%)", backdropFilter: "blur(16px)" }}
              >
                {/* User info */}
                <div className="px-3.5 py-2">
                  <div className="text-[11px] text-foreground/50 font-medium">{alias}</div>
                  {email && <div className="text-[10px] text-foreground/30 mt-0.5 truncate">{email}</div>}
                </div>

                <div className="my-1 border-t border-white/[0.06]" />

                {/* Preferences */}
                <button
                  ref={el => { itemsRef.current[0] = el }}
                  role="menuitem"
                  onClick={() => setSendWithEnter(!sendWithEnter)}
                  className="w-full flex items-center justify-between px-3.5 py-2 text-[12px] font-medium text-foreground/70 hover:bg-white/[0.06] transition-colors menu-item-stagger"
                  style={{ "--stagger": "0ms" } as React.CSSProperties}
                >
                  <span>Send with Enter</span>
                  <span className={`w-8 h-[18px] rounded-full flex items-center px-0.5 transition-colors ${sendWithEnter ? "bg-brand-teal justify-end" : "bg-white/10 justify-start"}`}>
                    <span className="w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-all duration-200" />
                  </span>
                </button>

                <div className="my-1 border-t border-white/[0.06]" />

                {/* Sign out */}
                <button
                  ref={el => { itemsRef.current[1] = el }}
                  role="menuitem"
                  onClick={() => { closeMenu(); signOut() }}
                  className="w-full flex items-center gap-2 px-3.5 py-2 text-[12px] font-medium text-foreground/70 hover:text-red-400 hover:bg-red-500/10 transition-colors menu-item-stagger"
                  style={{ "--stagger": "30ms" } as React.CSSProperties}
                >
                  <LogOut className="h-3.5 w-3.5" />
                  <span>Sign out</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* ── Content area ── */}
      {children}
    </div>
  )
}
