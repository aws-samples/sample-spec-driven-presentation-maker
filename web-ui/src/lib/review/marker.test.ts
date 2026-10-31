// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Reading a change request back from its chat message: the message the server built for the
 * shared fixture (tests/fixtures/review_submissions.json, `message_case`) parses back into
 * what was sent, also with the prefixes a chat send adds around it.
 */

import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"
import { parseReviewMessage } from "./marker"

interface MessageCase {
  id: string
  normalized: { note: string | null; comments: { name: string; slide: string; rect: number[]; text: string }[] }
  expected_message: string
}

const fixture = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../tests/fixtures/review_submissions.json"), "utf-8"),
) as { message_case: MessageCase }
const c = fixture.message_case
const message = c.expected_message
const byName = <T extends { name: string }>(list: T[]) => [...list].sort((a, b) => a.name.localeCompare(b.name))

describe("parseReviewMessage", () => {
  it("reads the id, note and comments back from the server's message", () => {
    const parsed = parseReviewMessage(message)
    expect(parsed?.id).toBe(c.id)
    expect(parsed?.note).toBe(c.normalized.note)
    expect(byName(parsed!.comments)).toEqual(byName(c.normalized.comments))
    // Slide by slide, in sent order
    expect(parsed!.comments.map(x => x.name)).toEqual(["A", "C", "B"])
  })

  it("finds the request behind the prefixes a send adds (Cloud history)", () => {
    const sent = `<!--sdpm:include_images=true-->\n[Attached: a.png]\n${message}`
    expect(parseReviewMessage(sent)?.id).toBe(c.id)
  })

  it.each([
    ["plain text", "直して"],
    ["a marker without a block", `[review:${c.id}] 直して`],
    ["a malformed id", message.replace(`[review:${c.id}]`, "[review:../x]")],
    ["a damaged block", message.replace('"slides":[', '"slides":')],
    ["a comment without a rect", message.replace(/"rect":\[[^\]]*\],/, "")],
    ["an unterminated block", message.slice(0, message.lastIndexOf("\n```"))],
  ])("returns null for %s", (_name, text) => {
    expect(parseReviewMessage(text)).toBeNull()
  })
})
