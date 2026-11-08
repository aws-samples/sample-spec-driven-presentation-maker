// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A compose task's report and the texts the orchestrator reads, built as Cloud builds them
 * (agent/modes/composer.py, agent/background.py, agent/compose_messaging.py); pure.
 *
 * - The report: `status` (cancelled when stopped; else partial, failed or completed),
 *   `generated_slides` (groups that finished, in group order), `failed_groups`, `partial`,
 *   `summaries` (slugs label → the group's text), `spec_warnings`, `notice`, `build`,
 *   `outline_check` (when something was generated and the task was not cancelled). Cloud's
 *   `build_error` is not used: Local composers rebuild the deck themselves, and `build` is
 *   `"stale"` only when the output may miss a slide (compose-run.ts decides), with the rebuild
 *   sentence for the deck's format in the notice.
 * - The cancelled notice differs from Cloud's in its first sentence only: Local composers may
 *   have rebuilt the deck before Stop.
 * - `<compose_result task status>` and `<message_composer_error group>` are escaped like
 *   Cloud's notes: `&`, `<`, `>` in the body, `"` and `'` too in attributes.
 */
import type { TaskStatus } from "./events"

/** How one group of the task ended. */
export interface GroupOutcome {
  slugs: string[]
  instruction: string
  status: "success" | "error" | "cancelled"
  /** The composer's last text. */
  summary: string
  error?: string
}

export interface ReportInput {
  groups: GroupOutcome[]
  outlineSlugs: string[]
  specWarnings?: unknown[]
  cancelled: boolean
  /** The output may not hold every slide's last version (only when something was generated, not cancelled). */
  stale: boolean
  outputFormat: "pptx" | "html"
  /** The deck's directory, as dispatched (the HTML rebuild sentence names it). */
  deckId: string
}

export const LOCAL_CANCELLED_NOTICE =
  "Stopped: the turn was cancelled; the deck may be partly built. " +
  "generated_slides lists the groups that finished; slides of the other " +
  "groups may be missing or incomplete. Do not call compose_slides again " +
  "unless the user asks."

const pyList = (items: string[]) => `[${items.map((item) => `'${item}'`).join(", ")}]`

/** The rebuild sentence of a stale output. */
export function rebuildSentence(outputFormat: "pptx" | "html", deckId: string, firstSlug: string): string {
  if (outputFormat === "html") {
    return "output.html may not hold the last version of every slide: call run_python(purpose=\"Rebuild output.html\", " +
      `deck_id="${deckId}", code="print('rebuild')", measure_slides=["${firstSlug}"]) once before telling the user the deck is ready; ` +
      "it rebuilds output.html."
  }
  return "output.pptx may not hold the last version of every slide: call generate_pptx(deck_id) once before telling the user the deck is ready."
}

/** The report of a task whose groups all ended (Cloud's key order). */
export function buildReport(input: ReportInput): Record<string, unknown> {
  const generated = input.groups.filter((g) => g.status === "success").flatMap((g) => g.slugs)
  const failed = input.groups.flatMap((g, i) => g.status === "success" ? [] : [{
    group_index: i + 1, slugs: g.slugs, instruction: g.instruction, error: g.error ?? (g.status === "cancelled" ? "cancelled" : "failed"),
  }])
  const total = input.groups.reduce((n, g) => n + g.slugs.length, 0)
  const partial = failed.length > 0 && generated.length > 0
  const summaries: Record<string, string> = {}
  for (const g of input.groups) if (g.summary) summaries[g.slugs.join(", ")] = g.summary
  const report: Record<string, unknown> = {
    status: input.cancelled ? "cancelled" : partial ? "partial" : failed.length ? "failed" : "completed",
    generated_slides: generated,
    failed_groups: failed,
    partial,
    summaries,
  }
  if (input.specWarnings?.length) report.spec_warnings = input.specWarnings
  let notice: string | null = null
  if (input.cancelled) notice = LOCAL_CANCELLED_NOTICE
  else if (failed.length) {
    const failedSlugs = [...new Set(failed.flatMap((f) => f.slugs))].sort()
    notice = `${generated.length}/${total} slides were generated; groups covering ` +
      `${pyList(failedSlugs)} failed. Successfully generated slides do NOT need ` +
      "regeneration. Tell the user which slides failed and why, and offer " +
      "to retry — on retry, call compose_slides again with ONLY the failed " +
      "groups (reuse each group's slugs and instruction from failed_groups)."
  }
  const stale = input.stale && generated.length > 0 && !input.cancelled
  if (stale) {
    const sentence = rebuildSentence(input.outputFormat, input.deckId, generated[0])
    notice = notice ? `${notice} ${sentence}` : sentence
  }
  if (notice) report.notice = notice
  if (stale) report.build = "stale"
  if (generated.length && !input.cancelled) {
    report.outline_check = {
      expected: input.outlineSlugs,
      missing: input.outlineSlugs.filter((slug) => !generated.includes(slug)),
      extra: generated.filter((slug) => !input.outlineSlugs.includes(slug)),
    }
  }
  return report
}

/** The `<compose_result>` status: the run could not run (`failed`), was stopped, or ended (also when partial). */
export function taskStatus(opts: { cancelled: boolean; failed: boolean }): TaskStatus {
  if (opts.failed) return "failed"
  return opts.cancelled ? "cancelled" : "completed"
}

/** The report of a dispatch the Local server could not start (an invalid result, a stopped period). */
export function notStartedReport(reason: string): Record<string, unknown> {
  return { status: "failed", notice: `The Local server could not start this compose: ${reason}. Tell the user.` }
}

const escapeBody = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
const escapeAttribute = (text: string) => escapeBody(text).replace(/"/g, "&quot;").replace(/'/g, "&#x27;")

/** `<compose_result task status>report</compose_result>` (Cloud's background.result_block). */
export function resultBlock(taskId: string, status: TaskStatus, reportJson: string): string {
  return `<compose_result task="${escapeAttribute(taskId)}" status="${escapeAttribute(status)}">${escapeBody(reportJson)}</compose_result>`
}

/** Cloud's text for a message no composer took, as `<message_composer_error group>`. */
export function messageComposerError(group: number, running: { group: number; slugs: string[] }[]): string {
  const text = running.length
    ? `No composer of group ${group} is running. Running groups: ${running.map((r) => `${r.group} (${r.slugs.join(", ")})`).join("; ")}.`
    : "No composer is running now: compose_slides has finished or has not started its composers."
  return `<message_composer_error group="${escapeAttribute(String(group))}">${escapeBody(text)}</message_composer_error>`
}
