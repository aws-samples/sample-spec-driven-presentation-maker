// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { IS_LOCAL } from "@/lib/mode"
import type { UploadedFile } from "@/services/uploadService"

/** Build [Attached:...] marker string for a single file. */
export function buildAttachedMarker(file: UploadedFile): string {
  if (IS_LOCAL && file.filePath) {
    const parts = [`path: "${file.filePath}"`]
    if (file.imagesDir) parts.push(`images: "${file.imagesDir}"`)
    if (file.colorAnalysis) {
      const colors = file.colorAnalysis.palette
        .map((c) => `${c.hex}(${Math.round(c.ratio * 100)}%)`)
        .join(" ")
      parts.push(`colors: ${colors}`)
      parts.push(`brightness: ${file.colorAnalysis.brightness}`)
      parts.push(`saturation: ${file.colorAnalysis.saturation}`)
    }
    return `[Attached: ${file.fileName} (${parts.join(", ")})]`
  }
  return `[Attached: ${file.fileName} (uploadId: ${file.uploadId})]`
}

/** Build markers for multiple files, joined by newline. */
export function buildAttachedMarkers(files: UploadedFile[]): string {
  return files.map(buildAttachedMarker).join("\n")
}
