// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleChatShell — Resizable side panel for style chat.
 *
 * Mirrors ChatPanelShell's visual appearance (header, resize handle, width memory)
 * but without Panel A/B, tabs, or deck-specific logic.
 */

"use client"

import { useRef, useEffect, useState, useCallback } from "react"
import { StyleChatPanel } from "./StyleChatPanel"
import { MessageSquare, PanelRightClose } from "lucide-react"

const CHAT_WIDTH_KEY = "sdpm-chat-width"
const DEFAULT_WIDTH = 440
const MIN_WIDTH = 360
const MAX_WIDTH_PX = 600

interface StyleChatShellProps {
  open: boolean
  onClose: () => void
  styleId: string
  styleName: string
  onStyleWritten?: () => void
  onStyleSaved?: (saved: { title: string; filename: string }) => void
}

export function StyleChatShell({ open, onClose, styleId, styleName, onStyleWritten, onStyleSaved }: StyleChatShellProps) {
  const panelRef = useRef<HTMLElement>(null)
  const [panelWidth, setPanelWidth] = useState(() => {
    if (typeof window === "undefined") return DEFAULT_WIDTH
    const saved = localStorage.getItem(CHAT_WIDTH_KEY)
    return saved ? Math.max(MIN_WIDTH, Math.min(Number(saved), MAX_WIDTH_PX)) : DEFAULT_WIDTH
  })
  const resizingRef = useRef(false)

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
        className="chat-panel fixed right-0 top-12 bottom-0 z-50 w-full sm:relative sm:right-auto sm:top-auto sm:bottom-auto sm:z-auto sm:h-full sm:flex-none"
        style={{ width: open ? panelWidth : 0 }}
      >
        <div
          className="chat-resize-handle hidden sm:flex"
          onMouseDown={handleResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize chat panel"
        />
        <div
          className="chat-panel-inner h-full flex flex-col bg-background-panel pb-4"
          style={{
            "--chat-panel-inner-w": `${panelWidth}px`,
            boxShadow: open
              ? "-1px 0 0 var(--border), -20px 0 40px oklch(0 0 0 / 30%)"
              : "none",
          } as React.CSSProperties}
        >
          {/* Header */}
          <div className="flex-none px-4 pt-3 pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-5 h-5 rounded-md flex items-center justify-center bg-brand-teal-soft">
                  <MessageSquare className="h-2.5 w-2.5 text-brand-teal" />
                </div>
                <span className="text-sm font-semibold tracking-[-0.01em] truncate max-w-[200px]">
                  {styleName || "Style Chat"}
                </span>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-foreground-muted hover:text-foreground hover:bg-background-hover transition-all"
                aria-label="Close chat panel"
              >
                <PanelRightClose className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="mx-4 border-t border-white/[0.06]" />

          <div className="flex-1 overflow-hidden">
            <div className="h-full">
              <StyleChatPanel
                styleId={styleId}
                onStyleWritten={onStyleWritten}
                onStyleSaved={onStyleSaved}
              />
            </div>
          </div>
        </div>{/* end chat-panel-inner */}
      </aside>
    </>
  )
}
