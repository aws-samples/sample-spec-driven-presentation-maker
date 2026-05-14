// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { IS_LOCAL } from "@/lib/mode"
import type { UploadedFile } from "@/services/uploadService"

/** Build [Attached:...] marker string for a single file. */
export function buildAttachedMarker(file: UploadedFile): string {
  // PPTX deck-structure: when upload_file produced a guide hint, include
  // it inline so the agent branches into the import-pptx guide instead of
  // probing list_workflows or treating the upload as generic reference
  // material. uploadId is still surfaced so the agent can call
  // import_attachment / read_uploaded_file later.
  if (file.guide && file.guideInstruction) {
    const parts = [
      `uploadId: ${file.uploadId}`,
      `guide: ${file.guide}`,
      `guideInstruction: ${JSON.stringify(file.guideInstruction)}`,
    ]
    if (file.suggestedName) parts.push(`suggestedName: "${file.suggestedName}"`)
    if (typeof file.slideCount === "number") parts.push(`slideCount: ${file.slideCount}`)
    if (file.themeHints) parts.push(`themeHints: ${JSON.stringify(file.themeHints)}`)
    return `[Attached: ${file.fileName} (${parts.join(", ")})]`
  }

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
