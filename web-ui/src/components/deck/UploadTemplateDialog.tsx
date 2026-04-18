// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * UploadTemplateDialog — Drag & drop .pptx upload with progress and toast feedback.
 *
 * UX highlights:
 * - Drag & drop + click to select
 * - Real upload progress via XHR (S3 PUT phase)
 * - Granular error messages (format / size / network)
 * - Success toast with action link
 * - Keyboard & screen reader friendly via shadcn Dialog
 */

"use client"

import { useCallback, useRef, useState } from "react"
import { Upload, FileUp, Sparkles } from "lucide-react"
import { toast } from "sonner"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Progress } from "@/components/ui/progress"

interface UploadTemplateDialogProps {
  idToken: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onUploaded?: () => void
}

const MAX_SIZE = 100 * 1024 * 1024

type Phase = "idle" | "presigning" | "uploading" | "registering" | "done"

interface UploadState {
  phase: Phase
  progress: number
}

async function getApiBaseUrl(): Promise<string> {
  const response = await fetch("/aws-exports.json")
  const config = await response.json()
  return config.apiBaseUrl || ""
}

/** Upload via XHR to get real progress. Returns uploadId on success. */
async function uploadWithProgress(
  file: File,
  idToken: string,
  onProgress: (pct: number) => void,
): Promise<string> {
  const base = await getApiBaseUrl()
  const presignRes = await fetch(`${base}uploads/presign`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name,
      contentType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      fileSize: file.size,
    }),
  })
  if (!presignRes.ok) {
    const msg = presignRes.status === 413 ? "File too large" : `Upload preparation failed (${presignRes.status})`
    throw new Error(msg)
  }
  const { uploadId, presignedUrl } = await presignRes.json()

  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("PUT", presignedUrl)
    xhr.setRequestHeader("Content-Type", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    })
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else reject(new Error(`S3 upload failed (${xhr.status})`))
    })
    xhr.addEventListener("error", () => reject(new Error("Network error during upload")))
    xhr.addEventListener("abort", () => reject(new Error("Upload was aborted")))
    xhr.send(file)
  })

  return uploadId
}

export function UploadTemplateDialog({
  idToken, open, onOpenChange, onUploaded,
}: UploadTemplateDialogProps) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [dragActive, setDragActive] = useState(false)
  const [state, setState] = useState<UploadState>({ phase: "idle", progress: 0 })
  const [fieldError, setFieldError] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  const reset = () => {
    setFile(null); setName(""); setDescription("")
    setState({ phase: "idle", progress: 0 }); setFieldError("")
  }

  const handleFile = useCallback((f: File | null) => {
    if (!f) return
    if (!f.name.toLowerCase().endsWith(".pptx")) {
      setFieldError("Only .pptx files are supported. Please select a PowerPoint file.")
      return
    }
    if (f.size > MAX_SIZE) {
      setFieldError(`File exceeds 100MB limit (current: ${(f.size / 1024 / 1024).toFixed(1)}MB)`)
      return
    }
    setFieldError("")
    setFile(f)
    if (!name) setName(f.name.replace(/\.pptx$/i, ""))
  }, [name])

  const handleUpload = async () => {
    if (!file || !name.trim()) return
    try {
      setState({ phase: "presigning", progress: 0 })
      const uploadId = await uploadWithProgress(
        file, idToken,
        (pct) => setState({ phase: "uploading", progress: pct }),
      )
      setState({ phase: "registering", progress: 100 })
      const base = await getApiBaseUrl()
      const res = await fetch(`${base}resources/user/templates`, {
        method: "POST",
        headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ uploadId, name: name.trim(), description }),
      })
      if (!res.ok) throw new Error(`Registration failed (${res.status})`)
      setState({ phase: "done", progress: 100 })
      toast.success(`Template "${name.trim()}" saved`, {
        description: "Ready to use in your next deck.",
      })
      onUploaded?.()
      setTimeout(() => { onOpenChange(false); reset() }, 600)
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Upload failed"
      toast.error("Upload failed", { description: msg })
      setState({ phase: "idle", progress: 0 })
    }
  }

  const isUploading = state.phase !== "idle" && state.phase !== "done"
  const phaseLabel =
    state.phase === "presigning" ? "Preparing…" :
    state.phase === "uploading"  ? `Uploading ${state.progress}%` :
    state.phase === "registering" ? "Analyzing template…" :
    state.phase === "done"       ? "Done" : ""

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!isUploading) { onOpenChange(o); if (!o) reset() } }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10">
              <Upload className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <DialogTitle>Upload Template</DialogTitle>
              <DialogDescription>Add a .pptx file to your personal templates</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4">
          {/* Dropzone */}
          <label
            onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault(); setDragActive(false)
              handleFile(e.dataTransfer.files?.[0] || null)
            }}
            className={`relative block rounded-xl border-2 border-dashed transition-all cursor-pointer
              ${dragActive ? "border-brand-teal bg-brand-teal/5" : "border-border/60 hover:border-border-hover hover:bg-background-hover"}
              ${file ? "py-4 px-4" : "py-8 px-4"}`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
              onChange={(e) => handleFile(e.target.files?.[0] || null)}
              className="sr-only"
              disabled={isUploading}
            />
            {file ? (
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-brand-teal/15 flex items-center justify-center flex-none">
                  <FileUp className="h-5 w-5 text-brand-teal" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{file.name}</p>
                  <p className="text-[11px] text-foreground-muted">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
                {!isUploading && (
                  <button
                    type="button"
                    onClick={(e) => { e.preventDefault(); setFile(null) }}
                    className="text-[11px] text-foreground-muted hover:text-foreground px-2 py-1 rounded-md hover:bg-muted"
                  >
                    Change
                  </button>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-center">
                <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center">
                  <Upload className="h-5 w-5 text-foreground-muted" />
                </div>
                <p className="text-sm font-medium">Drop a .pptx here or click to browse</p>
                <p className="text-[11px] text-foreground-muted">Max 100MB</p>
              </div>
            )}
          </label>

          {fieldError && (
            <p role="alert" className="flex items-start gap-1.5 text-xs text-red-400 bg-red-500/10 rounded-md px-3 py-2">
              <span>{fieldError}</span>
            </p>
          )}

          {/* Fields */}
          <div className="space-y-2">
            <label htmlFor="tpl-name" className="text-xs text-foreground-muted">Display name</label>
            <Input
              id="tpl-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={128}
              disabled={isUploading}
              placeholder="e.g. Corporate 2026"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="tpl-desc" className="text-xs text-foreground-muted">Description (optional)</label>
            <Textarea
              id="tpl-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={256}
              disabled={isUploading}
              rows={2}
              placeholder="What is this template for?"
            />
          </div>

          {/* Progress */}
          {isUploading && (
            <div className="space-y-2" aria-live="polite">
              <div className="flex items-center justify-between text-[11px] text-foreground-muted">
                <span className="flex items-center gap-1.5">
                  <Sparkles className="h-3 w-3 animate-pulse text-brand-teal" />
                  {phaseLabel}
                </span>
                {state.phase === "uploading" && <span>{state.progress}%</span>}
              </div>
              <Progress value={state.progress} />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isUploading}>
            Cancel
          </Button>
          <Button
            onClick={handleUpload}
            disabled={!file || !name.trim() || isUploading}
            className="bg-brand-teal hover:brightness-110 text-primary-foreground"
          >
            {isUploading ? phaseLabel : "Upload"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
