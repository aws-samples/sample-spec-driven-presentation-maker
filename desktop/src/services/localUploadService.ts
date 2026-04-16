/**
 * Local Upload Service — file import via local filesystem.
 *
 * Same interface as web-ui/src/services/uploadService.ts.
 * Copies files into deck workspace instead of S3.
 */

import { copyFile, mkdir, exists } from "@tauri-apps/plugin-fs";
import { join } from "@tauri-apps/api/path";
import type { UploadedFile } from "@/services/uploadService";

export { validateFile, canAddMoreFiles } from "@/services/uploadService";

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

  // Write file to deck workspace uploads directory
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
  return {
    uploadId,
    fileName: "",
    fileType: "",
    fileSize: 0,
    status: "completed",
  };
}
