/**
 * Local Upload Service — file import via local filesystem.
 *
 * Same interface as web-ui/src/services/uploadService.ts.
 * Copies files into deck workspace instead of S3.
 */

import { mkdir, exists } from "@tauri-apps/plugin-fs";
import { join } from "@tauri-apps/api/path";

const MAX_FILE_SIZE = 100 * 1024 * 1024;
const MAX_FILES = 5;
const ALLOWED_TYPES: Record<string, string> = {
  "text/plain": "txt", "text/markdown": "md", "application/json": "json",
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
  "image/png": "png",
};

export interface UploadedFile {
  uploadId: string; fileName: string; fileType: string; fileSize: number;
  status: "uploading" | "processing" | "completed" | "failed";
  extractedText?: string; imageUrl?: string;
}

export function validateFile(file: File): string | null {
  if (!ALLOWED_TYPES[file.type]) return `Unsupported file type: ${file.type || file.name.split(".").pop()}`;
  if (file.size > MAX_FILE_SIZE) return `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB).`;
  return null;
}

export function canAddMoreFiles(currentCount: number): boolean {
  return currentCount < MAX_FILES;
}

export async function uploadFile(
  file: File,
  _idToken: string,
  _sessionId: string,
  deckId?: string,
  onProgress?: (status: UploadedFile) => void,
): Promise<UploadedFile> {
  const uploadId = crypto.randomUUID();
  const uploaded: UploadedFile = {
    uploadId,
    fileName: file.name,
    fileType: file.type,
    fileSize: file.size,
    status: "uploading",
  };
  onProgress?.(uploaded);

  if (deckId) {
    const home = await (await import("@tauri-apps/api/path")).homeDir();
    const uploadsDir = await join(home, "Documents/SDPM-Presentations", deckId, "uploads");
    if (!(await exists(uploadsDir))) {
      await mkdir(uploadsDir, { recursive: true });
    }
    const dest = await join(uploadsDir, file.name);
    const buffer = await file.arrayBuffer();
    const { writeFile } = await import("@tauri-apps/plugin-fs");
    await writeFile(dest, new Uint8Array(buffer));
  }

  uploaded.status = "completed";
  onProgress?.(uploaded);
  return uploaded;
}

export async function pollUploadStatus(
  uploadId: string,
  _idToken: string,
): Promise<UploadedFile> {
  return { uploadId, fileName: "", fileType: "", fileSize: 0, status: "completed" };
}
