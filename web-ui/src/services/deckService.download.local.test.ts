// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** downloadDeckPptx (local): a download of the file route itself, with or without speaker notes. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/mode", () => ({ IS_LOCAL: true }))

import { downloadDeckPptx } from "./deckService"

describe("downloadDeckPptx (local)", () => {
  let clicked: string[]

  beforeEach(() => {
    clicked = []
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(new URL(this.href).pathname + new URL(this.href).search)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("downloads the route, with ?notes=without for the copy without speaker notes", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    await downloadDeckPptx("d1", "local")
    await downloadDeckPptx("d1", "local", { withNotes: false })
    expect(clicked).toEqual(["/api/decks/d1/pptx", "/api/decks/d1/pptx?notes=without"])
    expect(fetchMock).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
