// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Tool cards: a result is shown under its call's name; the deck a result names is its `deckId`,
 * else the last segment of an `output_dir` under the deck root (the root itself is no deck), and
 * the shown result carries it.
 */

import path from "path"
import { describe, expect, it } from "vitest"

import { DECK_ROOT } from "../deck-paths"
import { ToolTracker, withDeckId } from "./tools"

const DECK_DIR = path.resolve(DECK_ROOT, "20261101-1648-review")

describe("withDeckId", () => {
  it("takes the deck id from a deck's output_dir but not from the deck root", () => {
    expect(withDeckId({ output_dir: DECK_ROOT })).toEqual({ result: { output_dir: DECK_ROOT } })
    expect(withDeckId({ output_dir: `${DECK_ROOT}/` })).toEqual({ result: { output_dir: `${DECK_ROOT}/` } })
    expect(withDeckId({ output_dir: DECK_DIR })).toEqual({ result: { output_dir: DECK_DIR, deckId: "20261101-1648-review" }, deckId: "20261101-1648-review" })
  })

  it("keeps a deckId the result already names", () => {
    expect(withDeckId({ deckId: "d1", output_dir: DECK_DIR })).toEqual({ result: { deckId: "d1", output_dir: DECK_DIR }, deckId: "d1" })
  })

  it("finds no deck in other results", () => {
    expect(withDeckId({ styles: [] })).toEqual({ result: { styles: [] } })
  })
})

describe("ToolTracker", () => {
  it("shows a result under the name its call was given", () => {
    const tools = new ToolTracker()
    expect(tools.start("t1", "list_styles")).toEqual([{ kind: "data", payload: { toolStart: { toolUseId: "t1", name: "list_styles" } } }])
    expect(tools.use("t1", "list_styles", { a: 1 })).toEqual([{ kind: "data", payload: { toolUse: { toolUseId: "t1", name: "list_styles", input: { a: 1 } } } }])
    expect(tools.end("t1", "success", { count: 21 })).toEqual({
      events: [{ kind: "data", payload: { toolResult: { toolUseId: "t1", name: "list_styles", status: "success", content: "{\"count\":21}" } } }],
    })
  })

  it("returns the deck a result names", () => {
    const tools = new ToolTracker()
    tools.use("t1", "init_presentation", {})
    const ended = tools.end("t1", "success", { output_dir: DECK_DIR })
    expect(ended.deckId).toBe("20261101-1648-review")
    expect(JSON.parse((ended.events[0] as { payload: { toolResult: { content: string } } }).payload.toolResult.content)).toMatchObject({ deckId: "20261101-1648-review" })
  })
})
