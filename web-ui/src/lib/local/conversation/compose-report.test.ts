// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Compose reports (compose-report.ts) against the shared fixture `composeResult.json`, which
 * tests/test_agent_background.py parses with Cloud's `background.delivered()`: the report and its
 * key order, the `<compose_result>` text and its escaping; Cloud's two `message_composer` error
 * texts; a dispatch that could not start.
 */
import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

import { buildReport, messageComposerError, notStartedReport, resultBlock, taskStatus, type ReportInput } from "./compose-report"

interface Case { name: string; taskId: string; input: ReportInput; status: "completed" | "failed" | "cancelled"; report: Record<string, unknown>; text: string }
const fixture = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../../test/fixtures/composeResult.json"), "utf-8")) as { cases: Case[] }

describe("composeResult.json", () => {
  it.each(fixture.cases.map((c) => [c.name, c] as const))("%s: the report, its key order and its <compose_result>", (_name, c) => {
    const report = buildReport(c.input)
    expect(report).toEqual(c.report)
    expect(Object.keys(report)).toEqual(Object.keys(c.report))
    expect(taskStatus({ cancelled: c.input.cancelled, failed: false })).toBe(c.status)
    expect(resultBlock(c.taskId, c.status, JSON.stringify(report))).toBe(c.text)
  })

  it("covers completed, partial, cancelled and stale PPTX and HTML builds", () => {
    expect(fixture.cases.map((c) => c.report.status)).toEqual(["completed", "partial", "cancelled", "completed", "completed"])
    expect(fixture.cases.filter((c) => c.report.build === "stale").map((c) => c.name)).toEqual(["partial", "completed with a stale build", "stale HTML"])
  })
})

describe("texts", () => {
  it("escapes attributes and the body", () => {
    expect(resultBlock('a"b', "failed", "</compose_result> & more")).toBe('<compose_result task="a&quot;b" status="failed">&lt;/compose_result&gt; &amp; more</compose_result>')
  })

  it("tells running groups apart from none (Cloud's texts)", () => {
    expect(messageComposerError(3, [{ group: 1, slugs: ["a", "b"] }, { group: 2, slugs: ["c"] }]))
      .toBe('<message_composer_error group="3">No composer of group 3 is running. Running groups: 1 (a, b); 2 (c).</message_composer_error>')
    expect(messageComposerError(1, []))
      .toBe('<message_composer_error group="1">No composer is running now: compose_slides has finished or has not started its composers.</message_composer_error>')
  })

  it("reports a dispatch that could not start, and a run that failed", () => {
    expect(notStartedReport("deck_id is not a deck")).toEqual({ status: "failed", notice: "The Local server could not start this compose: deck_id is not a deck. Tell the user." })
    expect(taskStatus({ cancelled: true, failed: true })).toBe("failed")
  })
})
