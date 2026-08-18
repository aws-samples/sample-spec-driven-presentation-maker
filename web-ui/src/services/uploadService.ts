// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Stateless raw attachment upload service. Conversion happens on read/import. */

import { IS_LOCAL } from "@/lib/mode"

const MAX_FILE_SIZE = 100 * 1024 * 1024
const MAX_FILES = 5

const ALLOWED_TYPES = new Set([
  "text/plain",
  "text/markdown",
  "text/csv",
  "text/html",
  "application/json",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "image/svg+xml",
])

export interface UploadedFile {
  source: string
  fileName: string
  fileType: string
  fileSize: number
  status: "uploading" | "completed" | "failed"
}

let apiBaseUrl = ""

async function getApiBaseUrl(): Promise<string> {
  if (apiBaseUrl) return apiBaseUrl
  const response = await fetch("/aws-exports.json")
  if (!response.ok) throw new Error("Failed to load API configuration")
  const config = await response.json()
  apiBaseUrl = config.apiBaseUrl || ""
  return apiBaseUrl
}

export function validateFile(file: File): string | null {
  if (!ALLOWED_TYPES.has(file.type)) {
    return `Unsupported file type: ${file.type || file.name.split(".").pop()}`
  }
  if (file.size > MAX_FILE_SIZE) {
    return `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 100MB.`
  }
  return null
}

export function canAddMoreFiles(currentCount: number): boolean {
  return currentCount < MAX_FILES
}

/** Upload raw bytes and return the source identifier embedded in the chat marker. */
export async function uploadFile(
  file: File,
  idToken: string,
  sessionId: string,
  onProgress?: (status: UploadedFile) => void,
): Promise<UploadedFile> {
  const uploaded: UploadedFile = {
    source: "",
    fileName: file.name,
    fileType: file.type,
    fileSize: file.size,
    status: "uploading",
  }
  onProgress?.(uploaded)

  if (IS_LOCAL) {
    const form = new FormData()
    form.append("file", file)
    form.append("sessionId", sessionId)
    const response = await fetch("/api/attachments", { method: "POST", body: form })
    const result = await response.json().catch(() => ({ error: "Upload failed" }))
    if (!response.ok || result.error || typeof result.source !== "string") {
      throw new Error(result.error || "Failed to store attachment")
    }
    uploaded.source = result.source
    uploaded.status = "completed"
    onProgress?.(uploaded)
    return uploaded
  }

  const base = await getApiBaseUrl()
  const presignResponse = await fetch(`${base}attachments/presign`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name,
      contentType: file.type,
      fileSize: file.size,
    }),
  })
  const presign = await presignResponse.json().catch(() => ({ error: "Presign failed" }))
  if (
    !presignResponse.ok
    || typeof presign.source !== "string"
    || typeof presign.presignedUrl !== "string"
    || !presign.requiredHeaders
    || typeof presign.requiredHeaders !== "object"
  ) {
    throw new Error(presign.error || "Failed to get attachment upload URL")
  }
  const requiredHeaders = Object.fromEntries(
    Object.entries(presign.requiredHeaders).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  )
  if (
    requiredHeaders["Content-Type"] !== file.type
    || requiredHeaders["If-None-Match"] !== "*"
    || requiredHeaders["x-amz-tagging"] !== "sdpm-class=attachment-source"
  ) {
    throw new Error("Invalid attachment upload contract")
  }

  uploaded.source = presign.source
  const putResponse = await fetch(presign.presignedUrl, {
    method: "PUT",
    headers: requiredHeaders,
    body: file,
  })
  if (!putResponse.ok) throw new Error("Failed to upload attachment")

  uploaded.status = "completed"
  onProgress?.(uploaded)
  return uploaded
}
