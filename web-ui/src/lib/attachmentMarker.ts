// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { UploadedFile } from "@/services/uploadService"

export interface AttachedMarker {
  v: 1
  name: string
  source: string
}

const PREFIX = "[Attached:"

/** Build the only supported attachment wire marker. */
export function buildAttachedMarker(file: UploadedFile): string {
  const payload: AttachedMarker = { v: 1, name: file.fileName, source: file.source }
  // Escape the envelope terminator even though it is valid inside JSON strings.
  const json = JSON.stringify(payload).replaceAll("]", "\\u005d")
  return `${PREFIX}${json}]`
}

export function buildAttachedMarkers(files: UploadedFile[]): string {
  return files.map(buildAttachedMarker).join("\n")
}

/** Parse valid v1 markers without regex assumptions about braces in JSON strings. */
export function parseAttachedMarkers(text: string): AttachedMarker[] {
  const markers: AttachedMarker[] = []
  let searchFrom = 0

  while (searchFrom < text.length) {
    const markerStart = text.indexOf(PREFIX, searchFrom)
    if (markerStart < 0) break
    const jsonStart = markerStart + PREFIX.length
    if (text[jsonStart] !== "{") {
      searchFrom = jsonStart
      continue
    }

    let depth = 0
    let inString = false
    let escaped = false
    let jsonEnd = -1
    for (let i = jsonStart; i < text.length; i++) {
      const char = text[i]
      if (inString) {
        if (escaped) escaped = false
        else if (char === "\\") escaped = true
        else if (char === '"') inString = false
        continue
      }
      if (char === '"') inString = true
      else if (char === "{") depth++
      else if (char === "}" && --depth === 0) {
        jsonEnd = i + 1
        break
      }
    }

    if (jsonEnd < 0 || text[jsonEnd] !== "]") {
      searchFrom = jsonStart + 1
      continue
    }

    try {
      const value = JSON.parse(text.slice(jsonStart, jsonEnd)) as Partial<AttachedMarker>
      if (value.v === 1 && typeof value.name === "string" && value.name && typeof value.source === "string" && value.source) {
        markers.push(value as AttachedMarker)
      }
    } catch {
      // Malformed user text is not an attachment marker.
    }
    searchFrom = jsonEnd + 1
  }

  return markers
}
