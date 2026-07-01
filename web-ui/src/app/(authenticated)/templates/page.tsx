// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Templates page — Browse, upload, and manage PPTX templates.
 *
 * Design: Dark editorial × minimal luxury. Notion/Slack quality line.
 * Cards show template metadata (colors, fonts, layouts) at a glance.
 */

"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useAuth } from "@/hooks/useAuth"
import { AppShell } from "@/components/AppShell"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import {
  fetchTemplates,
  downloadTemplate,
  uploadTemplate,
  deleteTemplate,
  updateTemplateDescription,
  renameTemplate,
  type TemplateEntry,
} from "@/services/deckService"
import { Download, Trash2, Upload, FileText, Type, LayoutGrid, X } from "lucide-react"

export default function TemplatesPage() {
  const auth = useAuth()
  const idToken = auth.user?.id_token
  const [templates, setTemplates] = useState<TemplateEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const refresh = useCallback(async () => {
    if (!idToken) return
    const t = await fetchTemplates(idToken)
    setTemplates(t)
    setLoading(false)
  }, [idToken])

  useEffect(() => { refresh() }, [refresh])

  const handleDownload = async (name: string) => {
    if (!idToken) return
    await downloadTemplate(name, idToken)
  }

  const handleUpdateDescription = async (name: string, description: string) => {
    if (!idToken) return
    const result = await updateTemplateDescription(name, description, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    setTemplates(prev => prev.map(t => t.name === name ? { ...t, description } : t))
  }

  const handleRename = async (oldName: string, newName: string): Promise<string | null> => {
    if (!idToken) return "Not authenticated"
    if (!/^[a-zA-Z0-9_-]+$/.test(newName)) return "Letters, numbers, hyphens, underscores only"
    if (templates.some(t => t.name === newName)) return "Name already exists"
    const result = await renameTemplate(oldName, newName, idToken)
    if (result.error) return result.error
    setTemplates(prev => prev.map(t => t.name === oldName ? { ...t, name: newName } : t))
    return null
  }

  const handleDelete = async (name: string) => {
    if (!idToken) return
    const result = await deleteTemplate(name, idToken)
    if (result.error) { showToast(result.error, "error"); return }
    setTemplates(prev => prev.filter(t => t.name !== name))
    setDeleteConfirm(null)
    showToast(`Deleted "${name}"`)
  }

  const handleUploadComplete = async () => {
    setUploadOpen(false)
    await refresh()
  }

  const userTemplates = templates.filter(t => t.source === "user")
  const builtinTemplates = templates.filter(t => t.source === "builtin")

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="max-w-5xl mx-auto px-5 sm:px-8 py-8 sm:py-12">
            <div className="mb-8">
              <h1 className="text-xl font-semibold tracking-[-0.02em]">Templates</h1>
              <p className="text-sm text-foreground-muted mt-1">Manage your PPTX presentation templates</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-[168px] rounded-xl bg-white/[0.03] animate-pulse" />
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-5xl mx-auto px-5 sm:px-8 py-8 sm:py-12">
            <div className="flex items-center justify-between mb-8">
              <div>
                <h1 className="text-xl font-semibold tracking-[-0.02em]">Templates</h1>
                <p className="text-sm text-foreground-muted mt-1">Manage your PPTX presentation templates</p>
              </div>
            </div>

            <div className="flex flex-col gap-10">
              {/* My Templates */}
              <section>
                <h2 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider mb-4">My Templates</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {userTemplates.map(t => (
                    <TemplateCard
                      key={t.name}
                      template={t}
                      onDownload={handleDownload}
                      onDelete={name => setDeleteConfirm(name)}
                      onEditDescription={handleUpdateDescription}
                      onRename={handleRename}
                    />
                  ))}
                  {/* Upload card */}
                  <button
                    className="rounded-xl border-2 border-dashed border-white/[0.08] hover:border-brand-teal/30 bg-transparent hover:bg-brand-teal/[0.03] flex flex-col items-center justify-center gap-3 transition-all duration-200 cursor-pointer group min-h-[120px]"
                    onClick={() => setUploadOpen(true)}
                  >
                    <Upload className="h-6 w-6 text-brand-teal/30 group-hover:text-brand-teal/60 transition-colors duration-200" />
                    <span className="text-xs text-foreground/30 group-hover:text-foreground/60 font-medium transition-colors duration-200">Upload Template</span>
                  </button>
                </div>
              </section>

              {/* Built-in Templates */}
              <section>
                <h2 className="text-xs font-semibold text-foreground-muted uppercase tracking-wider mb-4">Built-in Templates</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {builtinTemplates.map(t => (
                    <TemplateCard
                      key={t.name}
                      template={t}
                      onDownload={handleDownload}
                    />
                  ))}
                </div>
              </section>
            </div>
          </div>
        )}
      </div>

      {/* Upload dialog */}
      {uploadOpen && (
        <UploadDialog
          idToken={idToken!}
          onClose={() => setUploadOpen(false)}
          onComplete={handleUploadComplete}
          onError={msg => showToast(msg, "error")}
        />
      )}

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteConfirm}
        onOpenChange={(open) => { if (!open) setDeleteConfirm(null) }}
        title="Delete template"
        description={<>Are you sure you want to delete <span className="font-medium text-foreground">{deleteConfirm}</span>? This cannot be undone.</>}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteConfirm && handleDelete(deleteConfirm)}
      />

      {/* Toast */}
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

// ── Template Card ──

function TemplateCard({ template, onDownload, onDelete, onEditDescription, onRename }: {
  template: TemplateEntry
  onDownload: (name: string) => void
  onDelete?: (name: string) => void
  onEditDescription?: (name: string, description: string) => void
  onRename?: (oldName: string, newName: string) => Promise<string | null>
}) {
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(template.description || "")
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(template.name)
  const [renameError, setRenameError] = useState("")
  const colors = template.theme_colors || {}
  const paletteColors = [
    colors.accent1, colors.accent2, colors.accent3,
    colors.accent4, colors.accent5, colors.accent6,
  ].filter(Boolean) as string[]

  const bgColor = colors.background || null
  const textColor = colors.text || null
  const fonts = template.fonts || {}
  const fontDisplay = [fonts.halfwidth, fonts.fullwidth].filter(Boolean).join(" / ")

  const handleDescSubmit = () => {
    const trimmed = editValue.trim()
    if (trimmed !== (template.description || "")) {
      onEditDescription?.(template.name, trimmed)
    }
    setEditing(false)
  }

  const handleRenameSubmit = async () => {
    const trimmed = renameValue.trim()
    if (!trimmed || trimmed === template.name) { setRenaming(false); setRenameError(""); return }
    if (!/^[a-zA-Z0-9_-]+$/.test(trimmed)) { setRenameError("a-z, 0-9, hyphens, underscores"); return }
    const err = await onRename?.(template.name, trimmed)
    if (err) { setRenameError(err); return }
    setRenaming(false)
    setRenameError("")
  }

  return (
    <div className="group relative rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] transition-all duration-200 overflow-hidden">
      {/* Theme preview strip — shows background + text color identity */}
      {bgColor && (
        <div
          className="h-10 w-full flex items-center justify-center px-3"
          style={{ backgroundColor: bgColor }}
        >
          {textColor && (
            <span className="text-[11px] font-medium opacity-70 tracking-wide" style={{ color: textColor }}>
              Aa
            </span>
          )}
          {paletteColors.length > 0 && (
            <div className="flex items-center gap-1 ml-auto">
              {paletteColors.slice(0, 5).map((c, i) => (
                <div
                  key={i}
                  className="w-2.5 h-2.5 rounded-full ring-1 ring-black/10"
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
          )}
        </div>
      )}

      <div className="p-4">
        {/* Header: name + actions */}
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              {renaming ? (
                <span className="flex flex-col" onClick={e => e.stopPropagation()}>
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={e => { setRenameValue(e.target.value); setRenameError("") }}
                    onBlur={handleRenameSubmit}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); handleRenameSubmit() } if (e.key === "Escape") { setRenaming(false); setRenameValue(template.name); setRenameError("") } }}
                    className={`text-sm font-semibold bg-white/[0.06] rounded px-1.5 py-0.5 -ml-1.5 outline-none ring-1 transition-colors ${renameError ? "ring-red-400/60" : "ring-brand-teal/40 focus:ring-brand-teal/60"}`}
                  />
                  {renameError && <span className="text-[11px] text-red-400 mt-0.5">{renameError}</span>}
                </span>
              ) : (
                <h3
                  className={`text-sm font-semibold truncate ${onRename ? "cursor-text rounded px-1.5 py-0.5 -ml-1.5 hover:bg-white/[0.04] transition-colors" : ""}`}
                  onClick={onRename ? e => { e.stopPropagation(); setRenaming(true); setRenameValue(template.name) } : undefined}
                >
                  {template.name}
                </h3>
              )}
              {template.source === "user" && !renaming && (
                <span className="text-[11px] text-brand-teal/70 font-medium shrink-0">Custom</span>
              )}
            </div>
            {/* Description — click to edit for user templates */}
            {editing ? (
              <textarea
                autoFocus
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onBlur={handleDescSubmit}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleDescSubmit() } if (e.key === "Escape") { setEditValue(template.description || ""); setEditing(false) } }}
                rows={2}
                className="w-full mt-1 rounded-md bg-white/[0.04] border border-brand-teal/30 focus:border-brand-teal/50 px-2 py-1 text-xs text-foreground placeholder:text-foreground/25 resize-none outline-none transition-colors"
                placeholder="When should this template be used?"
              />
            ) : onEditDescription ? (
              <p
                className="text-xs text-foreground-muted mt-1 line-clamp-2 leading-relaxed cursor-text rounded px-1 -mx-1 hover:bg-white/[0.04] transition-colors"
                onClick={e => { e.stopPropagation(); setEditing(true) }}
              >
                {template.description || <span className="text-foreground/20 italic">Add description…</span>}
              </p>
            ) : template.description ? (
              <p className="text-xs text-foreground-muted mt-1 line-clamp-2 leading-relaxed">{template.description}</p>
            ) : null}
          </div>

          {/* Action buttons — fade in on hover */}
          <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
            <button
              onClick={() => onDownload(template.name)}
              className="p-1.5 rounded-md text-foreground-muted hover:text-foreground hover:bg-white/[0.06] transition-colors"
              aria-label={`Download ${template.name}`}
            >
              <Download className="h-3.5 w-3.5" />
            </button>
            {onDelete && (
              <button
                onClick={() => onDelete(template.name)}
                className="p-1.5 rounded-md text-foreground-muted hover:text-red-400 hover:bg-red-500/10 transition-colors"
                aria-label={`Delete ${template.name}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Metadata row — only render if any metadata exists */}
        {(fontDisplay || template.layout_count > 0) && (
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-white/[0.04]">
          {/* Font */}
          {fontDisplay && (
            <div className="flex items-center gap-1.5 text-xs text-foreground-muted">
              <Type className="h-3 w-3 shrink-0 opacity-50" />
              <span>{fontDisplay}</span>
            </div>
          )}

          {/* Layout count */}
          {template.layout_count > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-foreground-muted ml-auto">
              <LayoutGrid className="h-3 w-3 shrink-0 opacity-50" />
              <span>{template.layout_count}</span>
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  )
}

// ── Upload Dialog ──

function UploadDialog({ idToken, onClose, onComplete, onError }: {
  idToken: string
  onClose: () => void
  onComplete: () => void
  onError: (msg: string) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [description, setDescription] = useState("")
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f?.name.endsWith(".pptx")) setFile(f)
  }

  const handleSubmit = async () => {
    if (!file) return
    setUploading(true)
    try {
      const result = await uploadTemplate(file, description, idToken)
      if (result.error) { onError(result.error); return }
      onComplete()
    } catch {
      onError("Failed to upload template")
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="border border-white/[0.1] rounded-xl w-full max-w-md mx-4 shadow-[0_24px_64px_oklch(0_0_0/70%)] animate-in fade-in zoom-in-95 duration-150"
        style={{ background: "oklch(0.14 0.005 260)" }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
          <h2 id="upload-title" className="text-sm font-semibold">Upload Template</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-foreground-muted hover:text-foreground transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-5 space-y-4">
          {/* Drop zone */}
          <div
            className={`relative rounded-lg border-2 border-dashed transition-all duration-200 ${
              dragOver
                ? "border-brand-teal/50 bg-brand-teal/[0.05]"
                : file
                  ? "border-brand-teal/30 bg-brand-teal/[0.03]"
                  : "border-white/[0.1] hover:border-white/[0.2]"
            } p-6 text-center cursor-pointer`}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            {file ? (
              <div className="flex items-center justify-center gap-2">
                <FileText className="h-5 w-5 text-brand-teal/70" />
                <span className="text-sm font-medium text-foreground/80">{file.name}</span>
                <button
                  onClick={e => { e.stopPropagation(); setFile(null) }}
                  className="p-0.5 rounded text-foreground-muted hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <>
                <Upload className="h-8 w-8 text-foreground/15 mx-auto mb-2" />
                <p className="text-sm text-foreground/40">
                  Drop <span className="text-foreground/60 font-medium">.pptx</span> here or click to browse
                </p>
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pptx"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) setFile(f)
                e.target.value = ""
              }}
            />
          </div>

          {/* Description */}
          <div>
            <label htmlFor="template-desc" className="block text-xs font-medium text-foreground-muted mb-1.5">
              Description <span className="text-foreground/30">(optional)</span>
            </label>
            <textarea
              id="template-desc"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="When should this template be used?"
              rows={2}
              className="w-full rounded-lg bg-white/[0.04] border border-white/[0.08] focus:border-brand-teal/40 focus:ring-1 focus:ring-brand-teal/20 px-3 py-2 text-sm text-foreground placeholder:text-foreground/25 resize-none outline-none transition-colors"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-white/[0.06]">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-lg border border-white/[0.08] hover:bg-white/[0.04] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!file || uploading}
            className="px-4 py-1.5 text-sm rounded-lg font-medium bg-brand-teal/20 text-brand-teal hover:bg-brand-teal/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {uploading ? (
              <>
                <span className="h-3 w-3 border-2 border-brand-teal/30 border-t-brand-teal rounded-full animate-spin" />
                Analyzing…
              </>
            ) : (
              "Upload"
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
