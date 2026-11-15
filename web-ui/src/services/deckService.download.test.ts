// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** downloadDeckPptx (cloud): one authorised API call, then a download of the presigned URL. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: false }))
vi.mock("@/lib/runtimeConfig", () => ({ loadRuntimeConfig: async () => ({ apiBaseUrl: "https://api.example/prod/" }) }))

import { downloadDeckPptx } from "./deckService"

const PRESIGNED = "https://bucket.s3.ap-northeast-1.amazonaws.com/pptx/d1/u.pptx?X-Amz-Signature=x"

describe("downloadDeckPptx", () => {
  let clicked: string[]

  beforeEach(() => {
    clicked = []
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.href)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("fetches the presigned URL with the token and downloads it", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ url: PRESIGNED, expiresIn: 900 })))
    vi.stubGlobal("fetch", fetchMock)
    await downloadDeckPptx("d 1", "tok")
    expect(fetchMock).toHaveBeenCalledWith("https://api.example/prod/decks/d%201/pptx", {
      headers: { Authorization: "Bearer tok" },
    })
    expect(clicked).toEqual([PRESIGNED])
    expect(document.querySelector("a[download]")).toBeNull()
  })

  it("throws and downloads nothing when the deck has no PPTX", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "PPTX not built yet" }), { status: 404 })))
    await expect(downloadDeckPptx("d1", "tok")).rejects.toThrow("404")
    expect(clicked).toEqual([])
  })
})
