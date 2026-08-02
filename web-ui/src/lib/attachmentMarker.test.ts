// SPDX-License-Identifier: MIT-0
import { describe, expect, it } from "vitest"
import { buildAttachedMarker, parseAttachedMarkers } from "./attachmentMarker"
import type { UploadedFile } from "@/services/uploadService"

function uploaded(fileName: string, source: string): UploadedFile {
  return { source, fileName, fileType: "text/plain", fileSize: 1, status: "completed" }
}

describe("attachment marker v1", () => {
  it("writes the exact compact JSON wire shape", () => {
    expect(buildAttachedMarker(uploaded("report.pdf", "/tmp/report.pdf"))).toBe(
      '[Attached:{"v":1,"name":"report.pdf","source":"/tmp/report.pdf"}]',
    )
  })

  it("round-trips quotes, braces, newlines, and envelope terminators safely", () => {
    const marker = buildAttachedMarker(uploaded('a"} ]\n.txt', "/tmp/a]b"))
    expect(marker).not.toContain("a]b")
    expect(parseAttachedMarkers(marker)).toEqual([
      { v: 1, name: 'a"} ]\n.txt', source: "/tmp/a]b" },
    ])
  })

  it("ignores malformed and unsupported markers", () => {
    expect(parseAttachedMarkers('[Attached:{"v":2,"name":"x","source":"y"}]')).toEqual([])
    expect(parseAttachedMarkers('[Attached:{not-json}]')).toEqual([])
  })

  it("parses multiple markers in surrounding text", () => {
    const text = `${buildAttachedMarker(uploaded("a.txt", "/a"))}\n${buildAttachedMarker(uploaded("b.txt", "/b"))}`
    expect(parseAttachedMarkers(text).map((marker) => marker.name)).toEqual(["a.txt", "b.txt"])
  })
})
