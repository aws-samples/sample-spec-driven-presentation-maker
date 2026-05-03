// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Styles page — Browse, manage, and create presentation styles.
 *
 * Lists user styles (with delete) and built-in styles.
 * Phase 3 will add style creation via agent chat.
 */

"use client"

import { useState, useEffect, useRef } from "react"
import { useAuth } from "@/hooks/useAuth"
import { AppShell } from "@/components/AppShell"
import { fetchStyles, fetchStyleHtml, pinStyle, saveUserStyle, deleteUserStyle, type StyleEntry } from "@/services/deckService"
import { StyleSlidePreview } from "@/components/StyleSlidePreview"
import { Star, Trash2, Palette, Download, Sparkles } from "lucide-react"

export default function StylesPage() {
  const auth = useAuth()
  const idToken = auth.user?.id_token
  const [styles, setStyles] = useState<StyleEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState<{ name: string; html: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  useEffect(() => {
    if (!idToken) return
    fetchStyles(idToken).then(s => { setStyles(s); setLoading(false) })
  }, [idToken])

  const handlePin = async (name: string) => {
    const style = styles.find(s => s.name === name)
    const newPinned = !style?.pinned
    setStyles(prev => prev.map(s => s.name === name ? { ...s, pinned: newPinned } : s))
    if (idToken) pinStyle(name, newPinned, idToken)
  }

  const handlePreview = async (name: string) => {
    setPreviewLoading(true)
    setPreview({ name, html: "" })
    if (idToken) {
      const html = await fetchStyleHtml(name, idToken)
      setPreview({ name, html })
    }
    setPreviewLoading(false)
  }

  const handleImport = async (file: File) => {
    if (!idToken) return
    const html = await file.text()
    if (!/<title>.*?<\/title>/i.test(html)) {
      showToast("Invalid style: HTML must contain a <title> tag.", "error")
      return
    }
    const name = file.name.replace(/\.html?$/i, "").replace(/[^a-zA-Z0-9_-]/g, "-")
    const result = await saveUserStyle(name, html, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    const updated = await fetchStyles(idToken)
    setStyles(updated)
    showToast(`Imported "${name}"`)
  }

  const handleDelete = async (name: string) => {
    if (!idToken) return
    const result = await deleteUserStyle(name, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    setStyles(prev => prev.filter(s => s.name !== name))
    if (preview?.name === name) setPreview(null)
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

  const userStyles = styles.filter(s => s.source === "user")
  const builtinStyles = styles.filter(s => s.source === "builtin")

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
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
        ) : preview ? (
          /* ── Full-width preview ── */
          <div>
            <div className="flex items-center gap-3 px-5 sm:px-8 py-3">
              <button
                onClick={() => setPreview(null)}
                className="text-sm text-foreground-muted hover:text-foreground transition-colors"
              >
                ← Back
              </button>
              <h2 className="text-sm font-semibold">{preview.name}</h2>
              <button
                onClick={() => handlePin(preview.name)}
                className={`p-1 rounded transition-colors ${
                  styles.find(s => s.name === preview.name)?.pinned
                    ? "text-brand-teal" : "text-foreground-muted hover:text-foreground"
                }`}
              >
                <Star className="h-3.5 w-3.5" fill={styles.find(s => s.name === preview.name)?.pinned ? "currentColor" : "none"} />
              </button>
              {styles.find(s => s.name === preview.name)?.source === "user" && (
                <>
                  <button
                    onClick={() => handleExport(preview.name)}
                    className="p-1 rounded text-foreground-muted hover:text-foreground transition-colors"
                    aria-label={`Export ${preview.name}`}
                  >
                    <Download className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setDeleteConfirm(preview.name)}
                    className="p-1 rounded text-foreground-muted hover:text-red-400 transition-colors"
                    aria-label={`Delete ${preview.name}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </>
              )}
            </div>
            <StyleSlidePreview html={preview.html} loading={previewLoading} />
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
                      onPreview={handlePreview}
                      onPin={handlePin}
                      onDelete={name => setDeleteConfirm(name)}
                      onExport={handleExport}
                    />
                  ))}
                  {/* Create with AI card + Import link */}
                  <div className="flex flex-col">
                    <button
                      className="aspect-[16/10] rounded-xl border-2 border-dashed border-white/[0.08] hover:border-brand-teal/30 bg-transparent hover:bg-brand-teal/[0.03] flex flex-col items-center justify-center gap-2 transition-all duration-200 cursor-pointer group"
                      onClick={() => {/* Phase 3: navigate to style creator */}}
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
                      onPreview={handlePreview}
                      onPin={handlePin}
                    />
                  ))}
                </div>
              </section>
            </div>
          </div>
        )}
      </div>

      {/* Delete confirmation dialog */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setDeleteConfirm(null)} onKeyDown={e => { if (e.key === "Escape") setDeleteConfirm(null) }}>
          <div className="bg-surface-secondary border border-white/[0.08] rounded-xl p-6 max-w-sm mx-4 shadow-2xl" role="alertdialog" aria-modal="true" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-semibold mb-2">Delete style</h3>
            <p className="text-sm text-foreground-muted mb-5">
              Are you sure you want to delete <span className="font-medium text-foreground">{deleteConfirm}</span>? This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-3 py-1.5 text-sm rounded-lg border border-white/[0.08] hover:bg-white/[0.04] transition-colors"
              >
                Cancel
              </button>
              <button
                autoFocus
                onClick={() => handleDelete(deleteConfirm)}
                className="px-3 py-1.5 text-sm rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

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
function StyleListCard({ style, onPreview, onPin, onDelete, onExport }: {
  style: StyleEntry
  onPreview: (name: string) => void
  onPin: (name: string) => void
  onDelete?: (name: string) => void
  onExport?: (name: string) => void
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
          <span className="text-sm font-medium truncate">{style.name}</span>
          <div className="flex items-center gap-1">
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
                className="p-1 rounded text-foreground-muted hover:text-foreground transition-colors opacity-0 group-hover:opacity-100 transition-opacity duration-150"
                aria-label={`Export ${style.name}`}
              >
                <Download className="h-3.5 w-3.5" />
              </button>
            )}
            {onDelete && (
              <button
                onClick={e => { e.stopPropagation(); onDelete(style.name) }}
                className="p-1 rounded text-foreground-muted hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 transition-opacity duration-150"
                aria-label={`Delete ${style.name}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
        {style.source === "user" && (
          <span className="text-[11px] text-brand-teal/70 font-medium mt-0.5 block">Custom</span>
        )}
      </div>
    </div>
  )
}
