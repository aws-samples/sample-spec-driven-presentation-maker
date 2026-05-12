// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Styles page — Browse, manage, and create presentation styles.
 *
 * Uses URL hash routing (useStyleWorkspace):
 * - No hash: style list grid
 * - #create: new style creation (Phase 3 agent chat)
 * - #{name}: style preview (user styles get chat panel in Phase 3)
 */

"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { useStyleWorkspace } from "@/hooks/useStyleWorkspace"
import { AppShell } from "@/components/AppShell"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import { fetchStyles, fetchStyleHtml, pinStyle, saveUserStyle, deleteUserStyle, renameUserStyle, type StyleEntry } from "@/services/deckService"
import { StyleSlidePreview } from "@/components/StyleSlidePreview"
import { StyleChatShell } from "@/components/chat/StyleChatShell"
import { Star, Trash2, Palette, Download, Sparkles, Copy, MessageSquare, Pencil, MoreHorizontal } from "lucide-react"

export default function StylesPage() {
  const auth = useAuth()
  const idToken = auth.user?.id_token
  const ws = useStyleWorkspace(idToken)

  const [styles, setStyles] = useState<StyleEntry[]>([])
  const [loading, setLoading] = useState(true)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [inlineRename, setInlineRename] = useState<string | null>(null)
  const [inlineRenameValue, setInlineRenameValue] = useState("")
  const [inlineRenameError, setInlineRenameError] = useState("")
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)
  const [chatOpen, setChatOpen] = useState(false)

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const refreshStyles = useCallback(async () => {
    if (!idToken) return
    const s = await fetchStyles(idToken)
    setStyles(s)
    setLoading(false)
  }, [idToken])

  useEffect(() => { refreshStyles() }, [refreshStyles])

  // When #create is visited, show name dialog and go back to list view
  useEffect(() => {
    if (ws.view.mode === "create") {
      ws.navigateToList()
      handleCreateStyle()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.view.mode])

  // Reset chat state when navigating away from preview
  useEffect(() => {
    if (ws.view.mode !== "preview") {
      setChatOpen(false)
    }
  }, [ws.view.mode])

  const handlePin = async (name: string) => {
    const style = styles.find(s => s.name === name)
    const newPinned = !style?.pinned
    setStyles(prev => prev.map(s => s.name === name ? { ...s, pinned: newPinned } : s))
    if (idToken) pinStyle(name, newPinned, idToken)
  }

  const handleImport = async (file: File) => {
    if (!idToken) return
    const html = await file.text()
    const name = file.name.replace(/\.html?$/i, "").replace(/[^a-zA-Z0-9_-]/g, "-")
    const result = await saveUserStyle(name, html, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    await refreshStyles()
    showToast(`Imported "${name}"`)
  }

  const handleDelete = async (name: string) => {
    if (!idToken) return
    const result = await deleteUserStyle(name, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    setStyles(prev => prev.filter(s => s.name !== name))
    if (ws.styleName === name) ws.navigateToList()
    setDeleteConfirm(null)
    showToast(`Deleted "${name}"`)
  }

  const handleExport = async (name: string) => {
    if (!idToken) return
    const html = await fetchStyleHtml(name, idToken)
    if (!html) return
    const blob = new Blob([html], { type: "text/html" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${name}.html`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleCopyToMyStyles = async (name: string) => {
    if (!idToken) return
    const html = await fetchStyleHtml(name, idToken)
    if (!html) return
    // Replace <title> with "Copy of {original}"
    const originalTitle = html.match(/<title>(.*?)<\/title>/i)?.[1] || name
    const newHtml = html.replace(/<title>.*?<\/title>/i, `<title>Copy of ${originalTitle}</title>`)
    const now = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    const filename = `style-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
    const result = await saveUserStyle(filename, newHtml, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    await refreshStyles()
    showToast(`Copied as "Copy of ${originalTitle}"`)
  }

  const handleCreateStyle = async () => {
    if (!idToken) return
    const now = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    const name = `style-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
    const html = `<!DOCTYPE html><html><head><title>Untitled Style</title></head><body><div class="slide" style="width:1920px;height:1080px;display:flex;align-items:center;justify-content:center;font-family:sans-serif;background:#1a1a2e;color:#fff;"><h1>Untitled Style</h1></div></body></html>`
    const result = await saveUserStyle(name, html, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    await refreshStyles()
    ws.navigateToStyle(name)
    setChatOpen(true)
  }

  const handleInlineRenameSubmit = async () => {
    if (!idToken || !inlineRename) return
    const newName = inlineRenameValue.trim()
    if (!newName || newName === inlineRename) { setInlineRename(null); setInlineRenameError(""); return }
    if (!/^[a-zA-Z0-9_-]+$/.test(newName)) { setInlineRenameError("Letters, numbers, hyphens, underscores only"); return }
    if (styles.some(s => s.name === newName)) { setInlineRenameError("Name already exists"); return }
    const result = await renameUserStyle(inlineRename, newName, idToken)
    if (result.error) { setInlineRenameError(result.error); return }
    setInlineRename(null)
    setInlineRenameError("")
    await refreshStyles()
  }

  const currentStyle = ws.styleName ? styles.find(s => s.name === ws.styleName) : null

  const userStyles = styles.filter(s => s.source === "user")
  const builtinStyles = styles.filter(s => s.source === "builtin")

  return (
    <AppShell
      deckName={ws.isWorkspace && ws.styleName ? ws.styleName : undefined}
      onBack={ws.isWorkspace ? ws.navigateToList : undefined}
    >
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-y-auto">
        {loading ? (
          /* ── Loading skeleton ── */
          <div className="max-w-5xl mx-auto px-5 sm:px-8 py-8 sm:py-12">
            <div className="flex items-center justify-between mb-8">
              <div>
                <h1 className="text-xl font-semibold tracking-[-0.02em]">Styles</h1>
                <p className="text-sm text-foreground-muted mt-1">Manage and preview presentation styles</p>
              </div>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="aspect-[16/10] rounded-xl bg-white/[0.03] animate-pulse" />
              ))}
            </div>
          </div>
        ) : ws.view.mode === "preview" && ws.styleName ? (
          /* ── Style preview ── */
          <div>
            <div className="flex items-center gap-3 px-5 sm:px-8 py-3">
              <button
                onClick={ws.navigateToList}
                className="text-sm text-foreground-muted hover:text-foreground transition-colors"
              >
                ← Back
              </button>
              <h2 className="text-sm font-semibold">{ws.styleName}</h2>
              <button
                onClick={() => handlePin(ws.styleName!)}
                className={`p-1 rounded transition-colors ${
                  currentStyle?.pinned
                    ? "text-brand-teal" : "text-foreground-muted hover:text-foreground"
                }`}
              >
                <Star className="h-3.5 w-3.5" fill={currentStyle?.pinned ? "currentColor" : "none"} />
              </button>
              {currentStyle?.source === "user" && (
                <>
                  <button
                    onClick={() => setChatOpen(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-brand-teal hover:text-brand-teal-bright border border-brand-teal/25 hover:border-brand-teal/40 bg-brand-teal/[0.06] hover:bg-brand-teal/[0.1] transition-colors"
                  >
                    <Sparkles className="h-3 w-3" />
                    Edit with AI
                  </button>
                  <PreviewMoreMenu
                    onExport={() => handleExport(ws.styleName!)}
                    onDelete={() => setDeleteConfirm(ws.styleName!)}
                  />
                </>
              )}
              {currentStyle?.source === "builtin" && (
                <button
                  onClick={() => handleCopyToMyStyles(ws.styleName!)}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs text-foreground-muted hover:text-foreground border border-white/[0.08] hover:border-white/[0.15] transition-colors"
                >
                  <Copy className="h-3 w-3" />
                  Copy to My Styles
                </button>
              )}
            </div>
            <StyleSlidePreview html={ws.previewHtml} loading={ws.previewLoading} />
          </div>
        ) : ws.view.mode === "create" ? (
          /* ── Create new style → creates Untitled Style and navigates ── */
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <Sparkles className="h-12 w-12 text-brand-teal/20 mx-auto mb-4" />
              <h2 className="text-sm font-semibold mb-1">Create with AI</h2>
              <p className="text-xs text-foreground-muted mb-4">Creating your new style…</p>
              <button
                onClick={ws.navigateToList}
                className="mt-4 px-3 py-1.5 text-xs rounded-lg border border-white/[0.08] hover:bg-white/[0.04] transition-colors"
              >
                ← Back to Styles
              </button>
            </div>
          </div>
        ) : (
          /* ── Style grid ── */
          <div className="max-w-5xl mx-auto px-5 sm:px-8 py-8 sm:py-12">
            <div className="flex items-center justify-between mb-8">
              <div>
                <h1 className="text-xl font-semibold tracking-[-0.02em]">Styles</h1>
                <p className="text-sm text-foreground-muted mt-1">Manage and preview presentation styles</p>
              </div>
            </div>
            <div className="flex flex-col gap-10">
              {/* User styles */}
              <section>
                <h2 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider mb-4">My Styles</h2>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                  {userStyles.map(style => (
                    <StyleListCard
                      key={style.name}
                      style={style}
                      onPreview={ws.navigateToStyle}
                      onPin={handlePin}
                      onDelete={name => setDeleteConfirm(name)}
                      onExport={handleExport}
                      onRename={name => { setInlineRename(name); setInlineRenameValue(name); setInlineRenameError("") }}
                      isRenaming={inlineRename === style.name}
                      renameValue={inlineRenameValue}
                      renameError={inlineRename === style.name ? inlineRenameError : ""}
                      onRenameChange={v => { setInlineRenameValue(v); setInlineRenameError("") }}
                      onRenameSubmit={handleInlineRenameSubmit}
                      onRenameCancel={() => { setInlineRename(null); setInlineRenameError("") }}
                    />
                  ))}
                  {/* Create with AI card + Import link */}
                  <div className="flex flex-col">
                    <button
                      className="aspect-[16/10] rounded-xl border-2 border-dashed border-white/[0.08] hover:border-brand-teal/30 bg-transparent hover:bg-brand-teal/[0.03] flex flex-col items-center justify-center gap-2 transition-all duration-200 cursor-pointer group"
                      onClick={handleCreateStyle}
                    >
                      <Sparkles className="h-6 w-6 text-brand-teal/30 group-hover:text-brand-teal/60 transition-colors duration-200" />
                      <span className="text-xs text-foreground/30 group-hover:text-foreground/60 font-medium transition-colors duration-200">Create with AI</span>
                    </button>
                    <button
                      className="mt-2 py-1.5 text-xs text-foreground/25 hover:text-foreground/50 transition-colors text-center"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      Import Style
                    </button>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".html,.htm"
                    className="hidden"
                    onChange={e => {
                      const file = e.target.files?.[0]
                      if (file) handleImport(file)
                      e.target.value = ""
                    }}
                  />
                </div>
              </section>

              {/* Built-in styles */}
              <section>
                <h2 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider mb-4">Built-in Styles</h2>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                  {builtinStyles.map(style => (
                    <StyleListCard
                      key={style.name}
                      style={style}
                      onPreview={ws.navigateToStyle}
                      onPin={handlePin}
                    />
                  ))}
                </div>
              </section>
            </div>
          </div>
        )}
        </div>

        {/* Style Chat Panel (side panel) */}
        {ws.view.mode === "preview" && currentStyle?.source === "user" && (
          <StyleChatShell
            open={chatOpen}
            onClose={() => setChatOpen(false)}
            styleId={ws.styleName!}
            styleName={ws.styleName!}
            onStyleWritten={() => ws.refreshPreview()}
            onStyleSaved={async (saved) => {
              showToast(`Style saved: ${saved.title}`, "success")
              await refreshStyles()
            }}
          />
        )}
      </div>

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={!!deleteConfirm}
        onOpenChange={(open) => { if (!open) setDeleteConfirm(null) }}
        title="Delete style"
        description={<>Are you sure you want to delete <span className="font-medium text-foreground">{deleteConfirm}</span>? This cannot be undone.</>}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteConfirm && handleDelete(deleteConfirm)}
      />

      {/* Toast notification */}
      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-lg text-sm font-medium shadow-lg animate-in fade-in slide-in-from-bottom-2 duration-200 ${
          toast.type === "error" ? "bg-red-500/20 text-red-300 border border-red-500/20" : "bg-brand-teal/20 text-brand-teal border border-brand-teal/20"
        }`}>
          {toast.message}
        </div>
      )}
    </AppShell>
  )
}

/** Style card for the /styles list page. */
function StyleListCard({ style, onPreview, onPin, onDelete, onExport, onRename, isRenaming, renameValue, renameError, onRenameChange, onRenameSubmit, onRenameCancel }: {
  style: StyleEntry
  onPreview: (name: string) => void
  onPin: (name: string) => void
  onDelete?: (name: string) => void
  onExport?: (name: string) => void
  onRename?: (name: string) => void
  isRenaming?: boolean
  renameValue?: string
  renameError?: string
  onRenameChange?: (v: string) => void
  onRenameSubmit?: () => void
  onRenameCancel?: () => void
}) {
  const cardRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.15)

  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / 1920))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div
      ref={cardRef}
      className="group relative rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] transition-all duration-200 cursor-pointer"
      onClick={() => onPreview(style.name)}
    >
      {/* Cover preview */}
      <div className="relative overflow-hidden bg-black/20" style={{ height: 1080 * scale }}>
        {style.coverHtml ? (
          <iframe
            srcDoc={style.coverHtml}
            className="pointer-events-none"
            style={{ width: 1920, height: 1080, transform: `scale(${scale})`, transformOrigin: "top left", border: "none" }}
            tabIndex={-1}
            sandbox="allow-same-origin"
            title={style.name}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <Palette className="h-8 w-8 text-foreground/10" />
          </div>
        )}
      </div>

      {/* Info bar */}
      <div className="px-3 py-2.5 border-t border-white/[0.06]">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium truncate flex-1 min-w-0">
            {isRenaming ? (
              <span className="flex flex-col" onClick={e => e.stopPropagation()}>
                <input
                  autoFocus
                  value={renameValue}
                  onChange={e => onRenameChange?.(e.target.value)}
                  onBlur={onRenameSubmit}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); onRenameSubmit?.() } if (e.key === "Escape") onRenameCancel?.() }}
                  className={`w-full text-sm font-medium bg-white/[0.06] rounded px-1.5 py-0.5 -ml-1.5 outline-none ring-1 transition-colors ${renameError ? "ring-red-400/60" : "ring-brand-teal/40 focus:ring-brand-teal/60"}`}
                />
                {renameError && <span className="text-[11px] text-red-400 mt-0.5">{renameError}</span>}
              </span>
            ) : (
              <span
                className="group/name inline-flex items-center gap-1 cursor-text rounded px-1.5 py-0.5 -ml-1.5 hover:bg-white/[0.04] transition-colors"
                onClick={e => { if (onRename) { e.stopPropagation(); onRename(style.name) } }}
              >
                {style.name}
                {onRename && <Pencil className="h-3 w-3 text-foreground-muted/0 group-hover/name:text-foreground-muted transition-colors shrink-0" />}
              </span>
            )}
          </span>
          <div className="flex items-center gap-0.5 shrink-0">
            <button
              onClick={e => { e.stopPropagation(); onPin(style.name) }}
              className={`p-1 rounded transition-colors ${
                style.pinned ? "text-brand-teal" : "text-foreground-muted hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity duration-150"
              }`}
              aria-label={style.pinned ? `Unpin ${style.name}` : `Pin ${style.name}`}
            >
              <Star className="h-3.5 w-3.5" fill={style.pinned ? "currentColor" : "none"} />
            </button>
            {onExport && (
              <button
                onClick={e => { e.stopPropagation(); onExport(style.name) }}
                className="p-1 rounded text-foreground-muted hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity duration-150"
                aria-label={`Export ${style.name}`}
              >
                <Download className="h-3.5 w-3.5" />
              </button>
            )}
            {onDelete && (
              <button
                onClick={e => { e.stopPropagation(); onDelete(style.name) }}
                className="p-1 rounded text-foreground-muted hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity duration-150"
                aria-label={`Delete ${style.name}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
        {style.source === "user" && !isRenaming && (
          <span className="text-[11px] text-brand-teal/70 font-medium mt-0.5 block">Custom</span>
        )}
      </div>
    </div>
  )
}

/** ⋯ menu for preview header (Export / Delete). */
function PreviewMoreMenu({ onExport, onDelete }: { onExport: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-1 rounded text-foreground-muted hover:text-foreground transition-colors"
        aria-label="More actions"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 min-w-[140px] py-1 rounded-lg border border-white/[0.1] shadow-[0_8px_32px_oklch(0_0_0/50%)]" style={{ background: "oklch(0.14 0.005 260 / 98%)", backdropFilter: "blur(12px)" }}>
            <button
              onClick={() => { setOpen(false); onExport() }}
              className="w-full px-3 py-2 text-left text-sm text-foreground/70 hover:text-foreground hover:bg-white/[0.06] transition-colors flex items-center gap-2"
            >
              <Download className="h-3.5 w-3.5" /> Export
            </button>
            <button
              onClick={() => { setOpen(false); onDelete() }}
              className="w-full px-3 py-2 text-left text-sm text-foreground/70 hover:text-red-400 hover:bg-red-500/10 transition-colors flex items-center gap-2"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </button>
          </div>
        </>
      )}
    </div>
  )
}
