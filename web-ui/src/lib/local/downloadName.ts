// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Download file names for Local deck files: a copy of `safe_download_name` /
 * `attachment_disposition` in api/html_presign.py (the cloud API), so both modes save a
 * deck under the same name.
 */

const STRIP_CHARS = new Set(["/", "\\", "\"", "'"])
const MAX_NAME_CHARS = 120
/** Unicode "Other" (control, format/bidi, surrogate, private use, unassigned), as Python's category "C*". */
const OTHER_CHAR_RE = /\p{C}/u

const trimEnd = (s: string) => s.replace(/[ .]+$/, "")
const trim = (s: string) => trimEnd(s.replace(/^[ .]+/, ""))

/** File name for a downloaded deck: the title without control chars, path separators or quotes,
 *  at most 120 characters, ending in `ext` ("deck" + `ext` when nothing is left). */
export function safeDownloadName(name: unknown, ext: string): string {
  let text = Array.from(String(name ?? "")).filter((ch) => !STRIP_CHARS.has(ch) && !OTHER_CHAR_RE.test(ch)).join("")
  text = trim(text.split(/\s+/).filter(Boolean).join(" "))
  if (text.toLowerCase().endsWith(ext)) text = trimEnd(text.slice(0, -ext.length))
  text = trimEnd(Array.from(text).slice(0, MAX_NAME_CHARS).join(""))
  return `${text || "deck"}${ext}`
}

/** RFC 5987 value: every byte but ALPHA / DIGIT / "-._~" percent-encoded (Python `quote(safe="")`). */
function encodeRfc5987(value: string): string {
  return encodeURIComponent(value).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
}

/** Content-Disposition that downloads as the deck title (RFC 6266): an ASCII `filename=`
 *  fallback and the UTF-8 `filename*=`. Always a single ASCII line. */
export function attachmentDisposition(name: unknown, ext: string): string {
  const filename = safeDownloadName(name, ext)
  // eslint-disable-next-line no-control-regex -- control chars are already gone; this drops non-ASCII
  const asciiStem = trim(filename.slice(0, -ext.length).replace(/[^\x00-\x7f]/g, ""))
  return `attachment; filename="${asciiStem || "deck"}${ext}"; filename*=UTF-8''${encodeRfc5987(filename)}`
}
