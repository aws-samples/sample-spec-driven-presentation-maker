// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Upload Service — handles file upload via presigned URLs and processing.
 *
 * Flow: presign → S3 PUT → process → poll status
 */

const MAX_FILE_SIZE = 100 * 1024 * 1024 // 100MB
const MAX_FILES = 5

const IS_LOCAL = process.env.NEXT_PUBLIC_MODE === "local"

const ALLOWED_TYPES: Record<string, string> = {
  "text/plain": "txt",
  "text/markdown": "md",
  "application/json": "json",
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
  "image/png": "png",
}

export interface UploadedFile {
  uploadId: string
  fileName: string
  fileType: string
  fileSize: number
  status: "uploading" | "processing" | "completed" | "failed"
  extractedText?: string
  imageUrl?: string
}

let apiBaseUrl = ""

/**
 * Load the API base URL from aws-exports.json.
 *
 * @returns Base URL string
 */
async function getApiBaseUrl(): Promise<string> {
  if (apiBaseUrl) return apiBaseUrl
  const response = await fetch("/aws-exports.json")
  const config = await response.json()
  apiBaseUrl = config.apiBaseUrl || ""
  return apiBaseUrl
}

/**
 * Validate a file before upload.
 *
 * @param file - File to validate
 * @returns Error message or null if valid
 */
export function validateFile(file: File): string | null {
  if (!ALLOWED_TYPES[file.type]) {
    return `Unsupported file type: ${file.type || file.name.split(".").pop()}`
  }
  if (file.size > MAX_FILE_SIZE) {
    return `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 20MB.`
  }
  return null
}

/**
 * Check if adding more files would exceed the limit.
 *
 * @param currentCount - Current number of attached files
 * @returns True if more files can be added
 */
export function canAddMoreFiles(currentCount: number): boolean {
  return currentCount < MAX_FILES
}

/**
 * Upload a file via presigned URL and trigger processing.
 *
 * @param file - File to upload
 * @param idToken - Cognito ID token
 * @param sessionId - Chat session ID
 * @param deckId - Optional deck ID for context
 * @param onProgress - Optional callback for status updates
 * @returns UploadedFile with status
 */
export async function uploadFile(
  file: File,
  idToken: string,
  sessionId: string,
  deckId?: string,
  onProgress?: (status: UploadedFile) => void,
): Promise<UploadedFile> {
  // Local mode: POST to /api/upload (Next.js API Route → mcp-local/upload_tools)
  if (IS_LOCAL) {
    const form = new FormData()
    form.append("file", file)

    const uploaded: UploadedFile = {
      uploadId: "",
      fileName: file.name,
      fileType: file.type,
      fileSize: file.size,
      status: "uploading",
    }
    onProgress?.(uploaded)

    const resp = await fetch("/api/upload", { method: "POST", body: form })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: "Upload failed" }))
      throw new Error(err.error || "Failed to upload file")
    }
    const data = await resp.json()
    if (data.error) throw new Error(data.error)

    uploaded.uploadId = data.uploadId
    uploaded.status = data.status === "converted" || data.status === "completed" ? "completed" : "failed"
    onProgress?.(uploaded)
    return uploaded
  }

  const base = await getApiBaseUrl()

  // Step 1: Get presigned URL
  const presignResp = await fetch(`${base}uploads/presign`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name,
      contentType: file.type,
      fileSize: file.size,
    }),
  })

  if (!presignResp.ok) {
    const err = await presignResp.json()
    throw new Error(err.error || "Failed to get upload URL")
  }

  const { uploadId, presignedUrl } = await presignResp.json()

  const uploadedFile: UploadedFile = {
    uploadId,
    fileName: file.name,
    fileType: file.type,
    fileSize: file.size,
    status: "uploading",
  }
  onProgress?.(uploadedFile)

  // Step 2: Upload to S3
  const putResp = await fetch(presignedUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
  })

  if (!putResp.ok) {
    throw new Error("Failed to upload file to S3")
  }

  // Step 3: Trigger processing
  uploadedFile.status = "processing"
  onProgress?.(uploadedFile)

  const processResp = await fetch(`${base}uploads/${uploadId}/process`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, deckId: deckId || "" }),
  })

  if (!processResp.ok) {
    throw new Error("Failed to process file")
  }

  const processResult = await processResp.json()

  uploadedFile.status = processResult.status
  uploadedFile.extractedText = processResult.extractedText
  uploadedFile.imageUrl = processResult.imageUrl
  onProgress?.(uploadedFile)

  return uploadedFile
}

/**
 * Poll upload status until completed or failed.
 *
 * @param uploadId - Upload identifier
 * @param idToken - Cognito ID token
 * @param intervalMs - Polling interval in milliseconds
 * @param maxAttempts - Maximum polling attempts
 * @returns Final UploadedFile status
 */
export async function pollUploadStatus(
  uploadId: string,
  idToken: string,
  intervalMs: number = 2000,
  maxAttempts: number = 30,
): Promise<UploadedFile> {
  const base = await getApiBaseUrl()

  for (let i = 0; i < maxAttempts; i++) {
    const resp = await fetch(`${base}uploads/${uploadId}/status`, {
      headers: { Authorization: `Bearer ${idToken}` },
    })

    if (!resp.ok) throw new Error("Failed to check upload status")

    const result = await resp.json()

    if (result.status === "completed" || result.status === "failed") {
      return {
        uploadId: result.uploadId,
        fileName: result.fileName,
        fileType: result.fileType,
        fileSize: 0,
        status: result.status,
        extractedText: result.extractedText,
        imageUrl: result.imageUrl,
      }
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }

  throw new Error("Upload processing timed out")
}
