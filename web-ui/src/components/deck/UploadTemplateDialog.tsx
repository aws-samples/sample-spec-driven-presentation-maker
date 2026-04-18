// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * UploadTemplateDialog — Upload a .pptx as a personal template.
 */

"use client"

import { useRef, useState } from "react"
import { Upload, X } from "lucide-react"
import { uploadUserTemplate } from "@/services/resourcesService"

interface UploadTemplateDialogProps {
  idToken: string
  onClose: () => void
  onUploaded: () => void
}

export function UploadTemplateDialog({ idToken, onClose, onUploaded }: UploadTemplateDialogProps) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = (f: File | null) => {
    if (!f) return
    if (!f.name.toLowerCase().endsWith(".pptx")) {
      setError("Only .pptx files are supported")
      return
    }
    if (f.size > 100 * 1024 * 1024) {
      setError("File too large (max 100MB)")
      return
    }
    setError("")
    setFile(f)
    if (!name) setName(f.name.replace(/\.pptx$/i, ""))
  }

  const handleUpload = async () => {
    if (!file || !name.trim()) return
    setUploading(true)
    setError("")
    try {
      await uploadUserTemplate(file, name.trim(), description, idToken)
      onUploaded()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed")
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-popover border border-border rounded-xl shadow-xl w-full max-w-md mx-4 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10">
              <Upload className="h-5 w-5 text-blue-400" />
            </div>
            <h3 className="text-sm font-semibold">Upload Template</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3">
          {/* File input */}
          <div>
            <label className="text-xs text-foreground-muted mb-1 block">File (.pptx)</label>
            <input
              ref={inputRef}
              type="file"
              accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
              onChange={(e) => handleFile(e.target.files?.[0] || null)}
              className="w-full text-xs text-foreground-secondary file:mr-2 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:bg-muted file:text-xs file:text-foreground hover:file:bg-muted/80"
            />
            {file && (
              <p className="text-[11px] text-foreground-muted mt-1">
                {file.name} · {(file.size / 1024).toFixed(1)} KB
              </p>
            )}
          </div>

          {/* Name */}
          <div>
            <label className="text-xs text-foreground-muted mb-1 block">Display name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={128}
              className="w-full px-3 py-2 text-sm bg-muted/50 border border-border/40 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-xs text-foreground-muted mb-1 block">Description (optional)</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={256}
              className="w-full px-3 py-2 text-sm bg-muted/50 border border-border/40 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400 bg-red-500/10 rounded-md px-3 py-2">{error}</p>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-lg hover:bg-muted transition-colors"
            disabled={uploading}
          >
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={!file || !name.trim() || uploading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-teal text-primary-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition-all"
          >
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  )
}
