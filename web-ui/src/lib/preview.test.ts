// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { isHtmlPreview, previewIdentity } from "./preview"

describe("isHtmlPreview", () => {
  it("detects presigned and relative .html URLs by pathname", () => {
    expect(isHtmlPreview("https://b.s3.ap-northeast-1.amazonaws.com/html/d1/preview/intro_17.html?X-Amz-Signature=abc")).toBe(true)
    expect(isHtmlPreview("/api/preview/d1/preview/intro.html?v=123")).toBe(true)
  })

  it("is false for images, empty values and a .html that is only in the query", () => {
    expect(isHtmlPreview("https://cdn.example.com/previews/d1/intro_17.webp?Signature=x")).toBe(false)
    expect(isHtmlPreview("/api/preview/d1/preview/intro.png")).toBe(false)
    expect(isHtmlPreview("/thumb.png?file=a.html")).toBe(false)
    expect(isHtmlPreview(null)).toBe(false)
    expect(isHtmlPreview(undefined)).toBe(false)
    expect(isHtmlPreview("")).toBe(false)
  })
})

describe("previewIdentity", () => {
  it("cloud: drops the (re-signed) query string", () => {
    expect(previewIdentity("https://b/html/d1/preview/a_1.html?X-Amz-Signature=1", false)).toBe("https://b/html/d1/preview/a_1.html")
  })

  it("local: keeps the whole URL, whose ?v= carries the file mtime", () => {
    expect(previewIdentity("/api/preview/d1/preview/a.html?v=42", true)).toBe("/api/preview/d1/preview/a.html?v=42")
  })
})
