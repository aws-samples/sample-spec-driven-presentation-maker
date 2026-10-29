// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Preview URL helpers shared by thumbnails, the deck carousel and workspace polling.
 */

import { IS_LOCAL } from "@/lib/mode"

/**
 * Whether a preview URL points at an HTML file (HTML deck thumbnail) rather than an image.
 * Works for absolute presigned URLs and relative local URLs (`/api/preview/...`).
 *
 * @param url - Preview URL (null/undefined → false)
 */
export function isHtmlPreview(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    return new URL(url, "http://localhost").pathname.toLowerCase().endsWith(".html")
  } catch {
    return false
  }
}

/**
 * The part of a preview URL that identifies its content, for change detection.
 *
 * Cloud URLs are re-signed on every poll, so only the path (which carries the
 * epoch or build id) identifies the file. Local URLs carry the file's mtime in
 * `?v=`, so the whole URL is the identity.
 *
 * @param url - Preview URL
 * @param local - Local mode (defaults to the build-time mode)
 */
export function previewIdentity(url: string, local: boolean = IS_LOCAL): string {
  return local ? url : url.split("?")[0]
}
