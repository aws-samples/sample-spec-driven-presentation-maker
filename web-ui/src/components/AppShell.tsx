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
 * @returns App shell with header and content area
 */

"use client"

import { ReactNode, useState, useRef, useEffect, useCallback } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useAuth } from "@/hooks/useAuth"
import { ChevronLeft, CircleUser, LogOut, Settings as SettingsIcon, Palette, GalleryVerticalEnd, LayoutTemplate } from "lucide-react"
import { Settings } from "@/components/Settings"
import { SdpmMark } from "@/components/SdpmMark"
import { CloudOnly } from "@/lib/mode"
import { useTranslations } from "next-intl"

/** Primary destinations: a text row on mobile, an icon rail with labels on desktop. */
const NAV_ITEMS = [
  { href: "/decks/", key: "decks", icon: GalleryVerticalEnd },
  { href: "/styles/", key: "styles", icon: Palette },
  { href: "/templates/", key: "templates", icon: LayoutTemplate },
] as const

interface AppShellProps {
  children: ReactNode
  deckName?: string
  onBack?: () => void
  /** Overrides the Decks link (e.g. leave the conversation at the centre of the home screen). */
  onNavDecks?: () => void
}

export function AppShell({ children, deckName, onBack, onNavDecks }: AppShellProps) {
  // The logo and the rail's Decks item go to the list in place, so the home conversation stays
  // (a plain link to /decks/ would load the page anew). On a deck: back to the list; on the
  // home screen with a conversation: scroll to the list below it.
  const onDecksClick = onBack
    ? (e: React.MouseEvent) => { e.preventDefault(); onBack() }
    : onNavDecks
      ? (e: React.MouseEvent) => { e.preventDefault(); onNavDecks() }
      : undefined
  const t = useTranslations("appShell")
  const { user, signOut } = useAuth()
  const pathname = usePathname()
  const profile = user?.profile as Record<string, unknown> | undefined
  const alias = (profile?.preferred_username as string) || (profile?.email as string)?.split("@")[0] || ""
  const email = (profile?.email as string) || ""
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuVisible, setMenuVisible] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const itemsRef = useRef<(HTMLButtonElement | null)[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)

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
    <div className="flex flex-col sm:flex-row h-screen relative z-10">
      {/* ── Header (mobile: top bar · desktop: left rail) ── */}
      <header
        className="header-glass safe-top flex-none flex items-center justify-between px-5 h-12 border-b border-border relative z-[70] sm:flex-col sm:justify-start sm:h-auto sm:w-20 sm:px-0 sm:pb-3 sm:gap-3 sm:border-b-0 sm:border-r"
        role="banner"
      >
        <nav className="flex items-center gap-2.5 sm:flex-col sm:gap-1 sm:mt-3" aria-label={t("mainNavigation")}>
          {deckName && onBack && (
            <button
              onClick={onBack}
              className="flex items-center gap-2 text-foreground-secondary hover:text-foreground transition-colors sm:hidden"
              aria-label={t("backToDecks")}
            >
              <ChevronLeft className="h-4 w-4" />
              <span className="text-sm font-semibold tracking-[-0.02em] truncate max-w-[200px]">
                {deckName}
              </span>
            </button>
          )}
          <div className={`items-center gap-2.5 sm:flex-col sm:gap-1 ${deckName && onBack ? "hidden sm:flex" : "flex"}`}>
            <Link href="/decks/" onClick={onDecksClick} className="flex items-center no-underline sm:mb-3" aria-label={t("decks")}>
              <div className="w-6 h-6 sm:w-9 sm:h-9 flex items-center justify-center">
                <SdpmMark className="h-[22px] w-[22px] sm:h-8 sm:w-8" />
              </div>
            </Link>
            <div className="flex items-center gap-0.5 ml-1 sm:ml-0 sm:flex-col sm:gap-1">
              {NAV_ITEMS.map(({ href, key, icon: Icon }) => {
                const active = pathname?.startsWith(href.replace(/\/$/, ""))
                // Client-side navigation: the rail stays, the language and the sign-in carry over,
                // and only the content changes (a plain <a> reloads the whole document).
                return (
                  <Link
                    key={key}
                    href={href}
                    onClick={key === "decks" ? onDecksClick : undefined}
                    aria-current={active ? "page" : undefined}
                    className={`group/nav px-2 py-1 rounded-md whitespace-nowrap text-sm font-medium no-underline transition-colors sm:flex sm:flex-col sm:items-center sm:gap-1 sm:w-[72px] sm:px-0 sm:py-1.5 ${
                      active ? "text-foreground" : "text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    <span className={`hidden sm:flex w-10 h-8 items-center justify-center rounded-lg transition-colors ${
                      active ? "bg-foreground/[0.09]" : "group-hover/nav:bg-background-hover"
                    }`}>
                      <Icon className="h-[18px] w-[18px]" strokeWidth={active ? 2 : 1.75} />
                    </span>
                    <span className="sm:text-[11px] sm:leading-none">{t(key)}</span>
                  </Link>
                )
              })}
            </div>
          </div>
        </nav>

        <div className="flex items-center gap-1.5 sm:flex-col sm:mt-auto sm:gap-2">
          {/* ── Settings ── */}
          <button
            onClick={() => setSettingsOpen(true)}
            className={`w-9 h-9 sm:w-10 sm:h-10 rounded-lg sm:rounded-xl flex items-center justify-center transition-all duration-200 ${
              settingsOpen
                ? "bg-foreground/[0.09] text-foreground"
                : "text-foreground-secondary hover:bg-background-hover hover:text-foreground"
            }`}
            aria-label={t("settings")}
            title={t("settings")}
          >
            <SettingsIcon className="h-4 w-4 sm:h-[18px] sm:w-[18px]" />
          </button>

          {/* ── User menu (cloud only: who is signed in, sign out) ── */}
          <CloudOnly>
            <div ref={menuRef} className="relative">
              <button
                ref={triggerRef}
                onClick={toggleMenu}
                className={`w-9 h-9 sm:w-10 sm:h-10 rounded-lg sm:rounded-xl flex items-center justify-center transition-all duration-200 ${
                  menuOpen
                    ? "bg-brand-teal-soft text-brand-teal"
                    : "text-foreground-secondary hover:bg-background-hover hover:text-foreground"
                }`}
                aria-label={t("userMenu")}
                aria-expanded={menuOpen}
                aria-haspopup="true"
              >
                <CircleUser className="h-4 w-4 sm:h-[18px] sm:w-[18px]" />
              </button>

              {menuOpen && (
                <div
                  role="menu"
                  aria-label={t("userMenu")}
                  className={`absolute right-0 top-full mt-1.5 sm:right-auto sm:top-auto sm:mt-0 sm:left-full sm:bottom-0 sm:ml-2 w-56 rounded-xl py-1.5 z-[60] border border-border-hover bg-popover shadow-[var(--shadow-float)] user-menu-enter ${menuVisible ? "user-menu-visible" : ""}`}
                >
                  {/* User info */}
                  <div className="px-3.5 py-2">
                    <div className="text-xs text-foreground-secondary font-medium">{alias}</div>
                    {email && <div className="text-[11px] text-foreground-muted mt-0.5 truncate">{email}</div>}
                  </div>

                  <div className="my-1 border-t border-border" />

                  {/* Sign out */}
                  <button
                    ref={el => { itemsRef.current[0] = el }}
                    role="menuitem"
                    onClick={() => { closeMenu(); signOut() }}
                    className="w-full flex items-center gap-2 px-3.5 py-2.5 text-sm font-medium text-foreground/70 hover:text-red-400 hover:bg-red-500/10 transition-colors menu-item-stagger"
                    style={{ "--stagger": "0ms" } as React.CSSProperties}
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span>{t("signOut")}</span>
                  </button>
                </div>
              )}
            </div>
          </CloudOnly>
        </div>
      </header>

      {/* ── Content area ── */}
      <div className="page-fade flex-1 min-w-0 min-h-0 flex flex-col">{children}</div>

      {/* Settings dialog */}
      <Settings open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  )
}
