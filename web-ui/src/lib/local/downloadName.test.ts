// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Same cases as tests/test_api_html_presign.py: Local and cloud save a deck under one name. */

import { describe, expect, it } from "vitest"
import { attachmentDisposition, safeDownloadName } from "./downloadName"

describe("safeDownloadName", () => {
  it.each([
    ["四半期レビュー", "四半期レビュー.pptx"],
    ["Q3 Review.pptx", "Q3 Review.pptx"],
    ["Q3 Review.PPTX", "Q3 Review.pptx"],
    ["", "deck.pptx"],
    [null, "deck.pptx"],
    ["...", "deck.pptx"],
    ["../../etc/passwd", "etcpasswd.pptx"],
    ["a\"b'c\\d/e", "abcde.pptx"],
    ["line\r\nbreak\tand\x00nul", "linebreakandnul.pptx"],
    ["bidi\u202eoverride\u200b", "bidioverride.pptx"],
    ["  spaced   out  ", "spaced out.pptx"],
  ])("%j → %j", (name, expected) => {
    expect(safeDownloadName(name, ".pptx")).toBe(expected)
  })

  it("keeps at most 120 characters of the title", () => {
    expect(safeDownloadName("資".repeat(500), ".pptx")).toBe(`${"資".repeat(120)}.pptx`)
  })
})

describe("attachmentDisposition", () => {
  it("encodes a Japanese title in filename* with an ASCII fallback", () => {
    expect(attachmentDisposition("四半期レビュー", ".pptx")).toBe(
      "attachment; filename=\"deck.pptx\"; filename*=UTF-8''%E5%9B%9B%E5%8D%8A%E6%9C%9F%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC.pptx",
    )
    expect(attachmentDisposition("営業資料 Q3 2026", ".pptx")).toMatch(/^attachment; filename="Q3 2026\.pptx"; filename\*=UTF-8''/)
  })

  it("percent-encodes the characters encodeURIComponent leaves alone", () => {
    expect(attachmentDisposition("A (draft)*!", ".pptx")).toBe(
      "attachment; filename=\"A (draft)*!.pptx\"; filename*=UTF-8''A%20%28draft%29%2A%21.pptx",
    )
  })

  it("never breaks out of the header", () => {
    const value = attachmentDisposition("x\"; filename=\"evil.exe\r\nSet-Cookie: a=b", ".pptx")
    expect(value).not.toMatch(/[\r\n]/)
    expect(value).toMatch(/^[\x20-\x7e]+$/)
    expect(value.split("\"")).toHaveLength(3)
    expect(() => new Headers({ "Content-Disposition": value })).not.toThrow()
  })
})
