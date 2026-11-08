// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Compose in the background (Cloud #512's shape, run by the Local server): the orchestrator's
 * `compose_slides` MCP tool only answers "dispatched"; this run starts the composers, follows them
 * and wakes the orchestrator once with `<compose_result>`.
 *
 * - **Dispatch.** A `compose_slides` end whose result says `dispatched` (recognised by the name its
 *   `tool_use` gave, conversation/index.ts) is read at a trust boundary (it came through kiro-cli),
 *   becomes `taskStart` instead of a tool result, and holds the chat's work period (`WorkHold`).
 *   One task runs per chat at a time; a later dispatch waits for it. A result that fails the check
 *   is shown as an error and reported to the orchestrator as a failed `<compose_result>`; one read
 *   in a stopped period starts nothing and reports the task cancelled.
 * - **Groups.** Up to MAX_PARALLEL_COMPOSERS groups of a task run at once, every startable one at
 *   the same moment; the rest start as groups end. Each group runs on a kiro-cli of its own
 *   (`pool.acquireForComposer`, which may also wait for a server-wide slot), in one session for
 *   `sdpm-composer` on the chat's model and effort, prompted with the dispatched values (the deck's
 *   absolute path). Its tools stream on the task card; its text is the group's summary.
 * - **Group end.** The prompt's answer (`end_turn` done; `cancelled`; another stop reason or an
 *   error failed), unless messages kiro-cli had not injected are left: they go into one follow-up
 *   prompt on the same session first. Then the session is closed (V3 deletes it) and the kiro-cli's
 *   process tree gets SIGTERM; its slot frees once the tree is gone (hosts.ts).
 * - **message_composer.** Routed from its `tool_use` (the input is complete there): a `_session/steer`
 *   to that group's own kiro-cli, prefixed as Cloud's; kept for the first prompt of a group that is
 *   waiting or starting; anything else is not delivered (the card's result is an error, and the
 *   orchestrator gets `<message_composer_error>`). The MCP tool's own result is never shown.
 * - **Task end.** Output check (the output is stale when two or more groups were prompted, or when
 *   it is older than the newest slide file), report (conversation/compose-report.ts), `taskEnd`, the
 *   `<compose_result>` delivered to the chat (a wake turn, a steer into a running turn, or kept for
 *   the next prompt), the hold released.
 * - **Stop** (`cancel`, idempotent): `session/cancel` to every running composer, starts aborted,
 *   waiting groups dropped, no prompt or steer from then on; each tree gets SIGTERM once its group
 *   answered, and every tree still alive COMPOSER_STOP_KILL_MS after Stop gets SIGKILL. A later
 *   call only switches the reason to the chat's kiro-cli exit (until `taskEnd`): every tree gets
 *   SIGKILL at once and the task ends failed, synchronously. `dropped` (Stop's settle timeout)
 *   ends the task cancelled at once; nothing is emitted after it. A timeout (Cloud's 60 minutes)
 *   ends the task failed the same way as Stop.
 * - A composer's exit fails its group only; a composer that cannot start fails its group with the
 *   start error's code, without a retry (the report's `failed_groups` lets the orchestrator retry).
 */
import fs from "fs"
import path from "path"

import type { AcpAnswer } from "./acp/transport"
import type { Chat, WorkHold } from "./chat"
import type { RunToolEnd, RunToolUse } from "./conversation"
import { buildReport, messageComposerError, notStartedReport, resultBlock, taskStatus, type GroupOutcome } from "./conversation/compose-report"
import { data, type ChatEvent, type LocalEvent, type TaskStatus } from "./conversation/events"
import { resolveDeckDir } from "./deck-paths"
import { COMPOSER_AGENT, pool, type Host, type HostSession, type SessionSink } from "./hosts"
import { basename } from "./pathUtils"
import { AgentStartError, AgentTimeoutError } from "./turnErrors"

/** Groups of one task that run at once (Cloud runs 10). The compose_slides docstring says the same number. */
export const MAX_PARALLEL_COMPOSERS = 4
/** After Stop, every composer tree still alive gets SIGKILL this late. */
export const COMPOSER_STOP_KILL_MS = 1000
/** A task's limit (Cloud's task timeout). */
export const COMPOSE_TASK_TIMEOUT_MS = 3_600_000
/** Cloud's prefix of a message from the orchestrator (agent/compose_messaging.py). */
export const COMPOSER_MESSAGE_PREFIX = "Message from the orchestrator while you work: "
/** How long a composer's session/close and session/delete may take before its tree is ended anyway. */
const CLOSE_TIMEOUT_MS = 10_000

const COMPOSE_TOOL = "compose_slides"
const MESSAGE_TOOL = "message_composer"
const TASK_ID = /^[0-9a-f]{12,32}$/
const SLUG = /^[A-Za-z0-9_-]{1,128}$/

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))
/** Read the group's state afresh (it changes while a start or a request is awaited). */
const hasEnded = (g: { state: string }) => g.state === "ended"
const isAbort = (error: unknown) => error instanceof Error && error.name === "AbortError"

/** A dispatched compose_slides result, checked. */
export interface Dispatch {
  taskId: string
  deckId: string
  outputFormat: "pptx" | "html"
  groups: { slugs: string[]; instruction: string }[]
  outlineSlugs: string[]
  specWarnings: unknown[]
}

/** Check a dispatched result (it came through kiro-cli); the reason when it does not pass. */
export function readDispatch(result: Record<string, unknown>): { dispatch: Dispatch } | { reason: string; taskId: string } {
  const taskId = typeof result.task_id === "string" && TASK_ID.test(result.task_id) ? result.task_id : ""
  const fail = (reason: string) => ({ reason, taskId })
  if (!taskId) return fail("task_id is not a task id")
  const deckId = result.deck_id
  if (typeof deckId !== "string" || !path.isAbsolute(deckId)) return fail("deck_id is not an absolute path")
  let real: string
  try {
    real = fs.realpathSync.native(deckId)
  } catch {
    return fail("deck_id does not exist")
  }
  if (resolveDeckDir(basename(deckId)) !== real) return fail("deck_id is not a deck of this server")
  if (result.output_format !== "pptx" && result.output_format !== "html") return fail("output_format is not pptx or html")
  const raw = result.slide_groups
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > 20) return fail("slide_groups must be a list of 1 to 20 groups")
  const seen = new Set<string>()
  const groups: Dispatch["groups"] = []
  for (const [i, group] of raw.entries()) {
    const g = (group ?? {}) as { group?: unknown; slugs?: unknown; instruction?: unknown }
    if (g.group !== i + 1) return fail(`group ${i + 1} is numbered ${String(g.group)}`)
    if (!Array.isArray(g.slugs) || g.slugs.length < 1 || g.slugs.length > 50) return fail(`group ${i + 1} must have 1 to 50 slugs`)
    for (const slug of g.slugs) {
      if (typeof slug !== "string" || !SLUG.test(slug)) return fail(`group ${i + 1} has an invalid slug`)
      if (seen.has(slug)) return fail(`slug '${slug}' is in two groups`)
      seen.add(slug)
    }
    if (typeof g.instruction !== "string" || g.instruction.length < 1 || g.instruction.length > 10_000) return fail(`group ${i + 1} has no valid instruction`)
    groups.push({ slugs: [...g.slugs] as string[], instruction: g.instruction })
  }
  const outline = result.outline_slugs
  if (!Array.isArray(outline) || !outline.every((slug) => typeof slug === "string")) return fail("outline_slugs is not a list of slugs")
  const warnings = Array.isArray(result.spec_warnings) ? result.spec_warnings : []
  return { dispatch: { taskId, deckId: real, outputFormat: result.output_format, groups, outlineSlugs: [...outline], specWarnings: warnings } }
}

/** What a group is doing. */
type GroupState = "waiting" | "starting" | "running" | "ended"

interface Group {
  index: number
  slugs: string[]
  instruction: string
  state: GroupState
  host: Host | null
  hs: HostSession | null
  readonly abort: AbortController
  /** Messages for the first prompt (they arrived while it waited or started). */
  readonly pending: string[]
  /** Steers kiro-cli queued and has not injected yet. */
  steers: { text: string; messageId?: string }[]
  /** At least one prompt was sent (the output check counts them). */
  prompted: boolean
  summary: string
  outcome: GroupOutcome | null
  startedAt: number
  promptAt: number
}

/** The composer session's events, for one group. */
class GroupSink implements SessionSink {
  readonly kind = "aux" as const
  constructor(private readonly task: ComposeTask, private readonly group: Group) {}
  onEvents(events: LocalEvent[]): void { this.task.groupEvents(this.group, events) }
  onHostExit(code: number | null): void { this.task.composerExited(this.group, code) }
  busy(): boolean { return true }
  lastActivity(): number { return Date.now() }
  release(): void {}
}

/** One dispatched compose task (see the header). */
export class ComposeTask implements WorkHold {
  readonly groups: Group[]
  private release: () => void = () => {}
  private stopped = false
  private reason: "stop" | "host_exit" | "timeout" | null = null
  private ended = false
  private isDropped = false
  private started = false
  private killTimer: ReturnType<typeof setTimeout> | null = null
  private timeoutTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly runner: ComposeRunner,
    private readonly chat: Chat,
    readonly toolUseId: string,
    readonly dispatch: Dispatch,
  ) {
    this.groups = dispatch.groups.map((g, i) => ({
      index: i + 1, slugs: g.slugs, instruction: g.instruction, state: "waiting", host: null, hs: null, abort: new AbortController(),
      pending: [], steers: [], prompted: false, summary: "", outcome: null, startedAt: 0, promptAt: 0,
    }))
  }

  private get id(): string {
    return this.dispatch.taskId
  }

  /** Take the period (before `start`). */
  hold(): void {
    this.release = this.chat.hold(this)
  }

  /** Start every startable group. */
  start(): void {
    if (this.started || this.ended) return
    this.started = true
    console.log("[compose] task %s: %d group(s) for deck %s", this.id, this.groups.length, this.dispatch.deckId)
    this.timeoutTimer = setTimeout(() => this.timedOut(), COMPOSE_TASK_TIMEOUT_MS)
    this.timeoutTimer.unref?.()
    this.startWaiting()
  }

  /** Groups still running (for `<message_composer_error>`). */
  running(): { group: number; slugs: string[] }[] {
    return this.groups.filter((g) => g.state !== "ended" && g.state !== "waiting").map((g) => ({ group: g.index, slugs: g.slugs }))
  }

  /** Route a message_composer call; resolves with whether it reached the group. */
  async message(group: number, text: string, usedAt: number): Promise<boolean> {
    const g = this.groups.find((candidate) => candidate.index === group)
    if (!g || this.stopped || this.ended || g.state === "ended") return false
    if (g.state === "waiting" || g.state === "starting" || !g.hs) {
      g.pending.push(text)
      console.log("[compose] task %s group %d: message kept for its first prompt", this.id, group)
      return true
    }
    const hs = g.hs
    let answer: { queued?: boolean; messageId?: string; dropped?: string }
    try {
      answer = await hs.steer(COMPOSER_MESSAGE_PREFIX + text)
    } catch (error) {
      console.warn("[compose] task %s group %d: steer failed: %s", this.id, group, errorText(error))
      return false
    }
    console.log("[compose] task %s group %d: steer sent %d ms after tool_use", this.id, group, Date.now() - usedAt)
    if (answer.queued !== true) {
      console.warn("[compose] task %s group %d: kiro-cli did not queue the message (%s)", this.id, group, answer.dropped ?? "not queued")
      return false
    }
    if (hasEnded(g) || g.hs !== hs) return false
    g.steers.push({ text: COMPOSER_MESSAGE_PREFIX + text, ...(answer.messageId ? { messageId: answer.messageId } : {}) })
    console.log("[compose] task %s group %d: message queued (messageId %s) for session %s on kiro-cli pid %s", this.id, group, answer.messageId ?? "-", hs.sessionId, hs.host.conn.pid)
    return true
  }

  // ── WorkHold ──

  cancel(): void {
    if (this.ended || this.isDropped) return
    const hostExit = this.chat.hs.host.exited
    if (!this.stopped) {
      this.stopped = true
      this.reason = hostExit ? "host_exit" : "stop"
      this.clearTimeout()
      console.log("[compose] task %s: %s; cancelling its composers", this.id, hostExit ? "the chat's kiro-cli exited" : "stopped")
      this.cancelGroups(hostExit ? "the chat's kiro-cli exited" : null)
      if (hostExit) this.hostExit()
      else this.armKill(COMPOSER_STOP_KILL_MS)
      this.maybeFinish()
      return
    }
    if (hostExit && this.reason !== "host_exit") {
      this.reason = "host_exit"
      this.hostExit()
    }
  }

  dropped(): void {
    if (this.ended || this.isDropped) return
    console.warn("[compose] task %s: its composers did not stop in time; ending it cancelled", this.id)
    for (const g of this.groups) if (g.state !== "ended") this.setOutcome(g, "cancelled")
    this.finish()
    this.isDropped = true
  }

  // ── Groups ──

  private startWaiting(): void {
    if (this.stopped || this.ended) return
    const active = this.groups.filter((g) => g.state === "starting" || g.state === "running").length
    let room = MAX_PARALLEL_COMPOSERS - active
    for (const g of this.groups) {
      if (room <= 0) break
      if (g.state !== "waiting") continue
      room--
      void this.startGroup(g)
    }
  }

  private async startGroup(g: Group): Promise<void> {
    g.state = "starting"
    g.startedAt = Date.now()
    this.emit(this.chat.conversation.tasks.starting(this.toolUseId, g.index))
    try {
      const host = await pool.acquireForComposer(this.chat.engine, {
        signal: g.abort.signal,
        onWait: () => console.log("[compose] task %s group %d: waiting for a composer slot", this.id, g.index),
      })
      g.host = host
      if (this.stopped) throw new DOMException("Request cancelled", "AbortError")
      // An abort during the open ends the tree with SIGKILL (the open then fails with kiro-cli's exit).
      const onAbort = () => { void host.end("SIGKILL") }
      g.abort.signal.addEventListener("abort", onAbort, { once: true })
      let hs: HostSession
      try {
        hs = (await host.openSession(COMPOSER_AGENT, { kind: "new" }, { sink: new GroupSink(this, g) })).hs
      } finally {
        g.abort.signal.removeEventListener("abort", onAbort)
      }
      g.hs = hs
      console.log("[compose] task %s group %d: kiro-cli pid %s ready %d ms after start", this.id, g.index, host.conn.pid, Date.now() - g.startedAt)
      await this.followModel(g, hs)
      if (this.stopped || hasEnded(g)) throw new DOMException("Request cancelled", "AbortError")
      g.state = "running"
      const text = [composerPrompt(this.dispatch, g), ...g.pending.splice(0).map((m) => COMPOSER_MESSAGE_PREFIX + m)].join("\n\n")
      this.prompt(g, text)
    } catch (error) {
      if (hasEnded(g)) return
      if (g.host) void g.host.end("SIGKILL")
      if (isAbort(error) || this.stopped) {
        this.groupEnded(g, "cancelled")
        return
      }
      const code = error instanceof AgentStartError ? error.code : error instanceof AgentTimeoutError ? "agent_timeout" : "agent_start_failed"
      console.warn("[compose] task %s group %d: the composer did not start (%s): %s", this.id, g.index, code, errorText(error))
      this.groupEnded(g, "error", `${code}: ${errorText(error)}`)
    }
  }

  /** The orchestrator's model and effort on the composer's session (a failure is logged, the group goes on). */
  private async followModel(g: Group, hs: HostSession): Promise<void> {
    const models = this.chat.hs.engine.models()
    if (!models) return
    try {
      await hs.engine.setModel({ model: models.current, ...(models.effort ? { effort: models.effort.current } : {}) })
    } catch (error) {
      console.warn("[compose] task %s group %d: could not set model %s: %s", this.id, g.index, models.current, errorText(error))
    }
  }

  private prompt(g: Group, text: string): void {
    const hs = g.hs!
    g.prompted = true
    g.summary = ""
    g.promptAt = Date.now()
    hs.prompt(text, (answer) => this.answered(g, hs, answer))
    console.log("[compose] task %s group %d: prompt sent (kiro-cli pid %s, session %s)", this.id, g.index, hs.host.conn.pid, hs.sessionId)
  }

  /** The composer session's events. */
  groupEvents(g: Group, events: LocalEvent[]): void {
    if (g.state === "ended") return
    const cards = this.chat.conversation.tasks
    for (const event of events) {
      if (event.type === "text") g.summary += event.text
      else if (event.type === "tool_use") this.emit(cards.tool(this.toolUseId, g.index, event.id, event.name))
      else if (event.type === "tool_end") this.emit(cards.toolEnd(this.toolUseId, g.index, event.id, event.status))
      else if (event.type === "steer_injected") {
        const at = g.steers.findIndex((s) => (event.messageId && s.messageId === event.messageId) || (event.content !== undefined && s.text === event.content))
        if (at >= 0) g.steers.splice(at, 1)
        else if (g.steers.length && !event.messageId) g.steers.shift()
        console.log("[compose] task %s group %d: kiro-cli injected a message", this.id, g.index)
      }
    }
  }

  private answered(g: Group, hs: HostSession, answer: AcpAnswer): void {
    if (g.state === "ended" || g.hs !== hs) return
    const ms = Date.now() - g.promptAt
    if (!answer.ok) {
      console.warn("[compose] task %s group %d: the prompt failed after %d ms: %s", this.id, g.index, ms, answer.error.message)
      this.groupEnded(g, this.stopped ? "cancelled" : "error", answer.error.message)
      return
    }
    const stopReason = (answer.result as { stopReason?: string } | undefined)?.stopReason ?? "end_turn"
    console.log("[compose] task %s group %d: answered %s after %d ms", this.id, g.index, stopReason, ms)
    if (stopReason === "end_turn" && g.steers.length && !this.stopped) {
      void this.followUp(g, hs)
      return
    }
    if (stopReason === "end_turn") this.groupEnded(g, "success")
    else if (stopReason === "cancelled") this.groupEnded(g, "cancelled")
    else this.groupEnded(g, "error", `stopped: ${stopReason}`)
  }

  /** Messages kiro-cli had not injected when the composer finished: one more prompt with them. */
  private async followUp(g: Group, hs: HostSession): Promise<void> {
    const texts = g.steers.splice(0).map((s) => s.text)
    try {
      await hs.clearSteers()
    } catch (error) {
      console.warn("[compose] task %s group %d: _session/steer/clear: %s", this.id, g.index, errorText(error))
    }
    if (hasEnded(g) || this.stopped || hs.host.exited) {
      if (!hasEnded(g)) this.groupEnded(g, this.stopped ? "cancelled" : "success")
      return
    }
    console.log("[compose] task %s group %d: %d message(s) arrived after the composer finished; sending them as a follow-up prompt", this.id, g.index, texts.length)
    this.prompt(g, texts.join("\n\n"))
  }

  /** A composer's kiro-cli exited: its group fails (the others go on). */
  composerExited(g: Group, code: number | null): void {
    if (g.state === "ended") return
    this.groupEnded(g, this.stopped && this.reason === "stop" ? "cancelled" : "error", `kiro-cli exited (code ${code})`)
  }

  private setOutcome(g: Group, status: GroupOutcome["status"], error?: string): void {
    g.state = "ended"
    g.outcome = { slugs: g.slugs, instruction: g.instruction, status, summary: g.summary.trim(), ...(error ? { error } : {}) }
    g.abort.abort()
  }

  /** A group ended: its card line, then its composer's session and tree are ended; the next group starts. */
  private groupEnded(g: Group, status: GroupOutcome["status"], error?: string): void {
    if (g.state === "ended") return
    const timedOut = this.reason === "timeout" && status === "cancelled"
    this.setOutcome(g, timedOut ? "error" : status, timedOut ? "timed out after 60 minutes" : error)
    this.emit(this.chat.conversation.tasks.groupEnd(this.toolUseId, g.index, g.outcome!.status === "success" ? "done" : "error"))
    void this.endComposer(g)
    this.startWaiting()
    this.maybeFinish()
  }

  /** Close (V3: delete) the composer's session, then end its tree. */
  private async endComposer(g: Group): Promise<void> {
    const host = g.host
    if (!host) return
    if (g.hs && !host.exited) {
      let timer: ReturnType<typeof setTimeout> | undefined
      try {
        await Promise.race([
          g.hs.close({ discard: true }),
          new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`no answer in ${CLOSE_TIMEOUT_MS} ms`)), CLOSE_TIMEOUT_MS) }),
        ])
      } catch (error) {
        console.warn("[compose] task %s group %d: closing session %s: %s", this.id, g.index, g.hs.sessionId, errorText(error))
      } finally {
        clearTimeout(timer)
      }
    } else g.hs?.drop()
    const at = Date.now()
    await host.end("SIGTERM")
    await host.gone
    console.log("[compose] task %s group %d: kiro-cli pid %s tree gone %d ms after SIGTERM (groups %s)", this.id, g.index, host.conn.pid, Date.now() - at, host.tree.groups().join(", ") || "-")
  }

  // ── Stop, exits, timeout ──

  /** Stop's (or a timeout's) cancel: no prompt or steer from now on. `failure`: the groups that end now fail with it. */
  private cancelGroups(failure: string | null): void {
    for (const g of this.groups) {
      if (g.state === "waiting") {
        if (failure) this.setOutcome(g, "error", failure)
        else this.setOutcome(g, this.reason === "timeout" ? "error" : "cancelled", this.reason === "timeout" ? "timed out after 60 minutes" : undefined)
        this.emit(this.chat.conversation.tasks.groupEnd(this.toolUseId, g.index, "error"))
      } else if (g.state === "starting") g.abort.abort()
      else if (g.state === "running") g.hs?.cancel()
    }
  }

  /** Every composer tree still alive gets SIGKILL `ms` from now (once). */
  private armKill(ms: number): void {
    if (this.killTimer) return
    this.killTimer = setTimeout(() => {
      this.killTimer = null
      for (const g of this.groups) if (g.host) void g.host.end("SIGKILL")
    }, ms)
    this.killTimer.unref?.()
  }

  /** The chat's kiro-cli exited: every composer tree gets SIGKILL now, and the task ends failed at once. */
  private hostExit(): void {
    if (this.killTimer) clearTimeout(this.killTimer)
    this.killTimer = null
    for (const g of this.groups) {
      if (g.host) void g.host.end("SIGKILL")
      if (g.state !== "ended") {
        this.setOutcome(g, "error", "the chat's kiro-cli exited")
        this.emit(this.chat.conversation.tasks.groupEnd(this.toolUseId, g.index, "error"))
      }
    }
    this.maybeFinish()
  }

  private timedOut(): void {
    this.timeoutTimer = null
    if (this.stopped || this.ended) return
    console.warn("[compose] task %s: timed out after %d minutes", this.id, COMPOSE_TASK_TIMEOUT_MS / 60_000)
    this.stopped = true
    this.reason = "timeout"
    this.cancelGroups(null)
    this.armKill(COMPOSER_STOP_KILL_MS)
    this.maybeFinish()
  }

  private clearTimeout(): void {
    if (this.timeoutTimer) clearTimeout(this.timeoutTimer)
    this.timeoutTimer = null
  }

  // ── Task end ──

  private maybeFinish(): void {
    if (this.ended || !this.groups.every((g) => g.state === "ended")) return
    this.finish()
  }

  private finish(): void {
    if (this.ended) return
    this.ended = true
    this.clearTimeout()
    const cancelled = this.reason === "stop" || this.isDropped
    const outcomes = this.groups.map((g) => g.outcome!)
    const generated = outcomes.some((o) => o.status === "success")
    const stale = generated && !cancelled && this.outputStale()
    const report = buildReport({
      groups: outcomes, outlineSlugs: this.dispatch.outlineSlugs, specWarnings: this.dispatch.specWarnings,
      cancelled, stale, outputFormat: this.dispatch.outputFormat, deckId: this.dispatch.deckId,
    })
    const status: TaskStatus = taskStatus({ cancelled, failed: this.reason === "host_exit" || this.reason === "timeout" })
    const content = JSON.stringify(report)
    this.emit([data({ taskEnd: { toolUseId: this.toolUseId, taskId: this.id, name: COMPOSE_TOOL, status, content } })])
    this.chat.conversation.tasks.close(this.toolUseId)
    const where = this.chat.deliver(resultBlock(this.id, status, content), "wake")
    console.log("[compose] task %s: ended %s (%s); delivered (%s)", this.id, status, report.status, where === "turn" ? "wake" : where)
    this.release()
    this.runner.taskEnded(this)
  }

  /** Whether the output may not hold every slide's last version (§4.5). */
  private outputStale(): boolean {
    if (this.groups.filter((g) => g.prompted).length >= 2) return true
    try {
      const output = path.join(this.dispatch.deckId, this.dispatch.outputFormat === "html" ? "output.html" : "output.pptx")
      if (!fs.existsSync(output)) return true
      const slides = path.join(this.dispatch.deckId, "slides")
      const newest = fs.existsSync(slides) ? Math.max(0, ...fs.readdirSync(slides).map((name) => fs.statSync(path.join(slides, name)).mtimeMs)) : 0 // nosemgrep: path-join-resolve-traversal — names from readdir of the checked deck
      return fs.statSync(output).mtimeMs < newest
    } catch (error) {
      console.warn("[compose] task %s: output check: %s; reporting the output stale", this.id, errorText(error))
      return true
    }
  }

  private emit(events: ChatEvent[]): void {
    if (this.isDropped) return
    for (const event of events) this.chat.push(event)
  }
}

/** The composer prompt: the values of orchestrator.md's delegation template (the deck's absolute path). */
function composerPrompt(dispatch: Dispatch, g: Group): string {
  return `deck_id: ${dispatch.deckId}\nassigned_slugs: ${g.slugs.join(", ")}\nmode: ${dispatch.outputFormat}\ntask_instruction: ${g.instruction}`
}

/** A chat's compose tasks: one runs at a time, later dispatches wait. */
export class ComposeRunner {
  private current: ComposeTask | null = null
  private readonly queue: ComposeTask[] = []
  /** message_composer calls by tool id: whether each reached its group (a promise while its steer is in flight). */
  private readonly messages = new Map<string, { input: Record<string, unknown>; outcome: Promise<boolean> | boolean }>()
  /** The orchestrator's MCP tool calls while a task runs: name and start. */
  private readonly toolStarts = new Map<string, { name: string; at: number }>()

  constructor(private readonly chat: Chat) {}

  /** The orchestrator's tool latency while a task runs (approval condition 1's evidence). */
  observe(events: LocalEvent[]): void {
    const task = this.current
    if (!task) return
    for (const event of events) {
      if (event.type === "tool_use") this.toolStarts.set(event.id, { name: event.name, at: Date.now() })
      else if (event.type === "tool_end") {
        const started = this.toolStarts.get(event.id)
        if (!started) continue
        this.toolStarts.delete(event.id)
        console.log("[compose] task %s: orchestrator tool %s waited %d ms (composers running: %d)", task.dispatch.taskId, started.name, Date.now() - started.at, task.running().length)
      }
    }
  }

  /** A call of compose_slides or message_composer (its card was shown). */
  toolUse(use: RunToolUse): void {
    if (use.name !== MESSAGE_TOOL) return
    const entry = this.messages.get(use.id)
    if (entry && entry.outcome !== false) return
    const { group, text } = use.input as { group?: unknown; text?: unknown }
    const complete = Number.isInteger(group) && typeof text === "string"
    const task = this.current
    this.messages.set(use.id, { input: use.input, outcome: complete && task ? task.message(group as number, text as string, Date.now()) : false })
  }

  /** Its end (the run answers it). */
  toolEnded(end: RunToolEnd): void {
    if (end.name === COMPOSE_TOOL) {
      this.dispatched(end)
      return
    }
    const entry = this.messages.get(end.id)
    this.messages.delete(end.id)
    const outcome = entry?.outcome ?? false
    if (typeof outcome === "boolean") {
      this.messageEnded(end, entry?.input, outcome)
      return
    }
    // The steer is still in flight: the period stays open until the card has its result.
    const release = this.chat.period ? this.chat.hold({ cancel: () => {}, dropped: () => {} }) : () => {}
    void outcome.then((delivered) => this.messageEnded(end, entry?.input, delivered)).finally(release)
  }

  /** A task ended (also one that never started: a Stop ends the waiting ones too); the next waiting one starts. */
  taskEnded(task: ComposeTask): void {
    const at = this.queue.indexOf(task)
    if (at >= 0) this.queue.splice(at, 1)
    if (this.current !== task) return
    this.current = null
    const next = this.queue.shift()
    if (next) this.begin(next)
  }

  private begin(task: ComposeTask): void {
    this.current = task
    task.start()
  }

  private dispatched(end: RunToolEnd): void {
    const chat = this.chat
    if (end.status !== "success" || end.result.status !== "dispatched") {
      // compose_slides refused the call (its own error answer): an ordinary tool result.
      this.push(chat.conversation.toolResult(end.id, end.status, end.result, COMPOSE_TOOL).events)
      return
    }
    const read = readDispatch(end.result)
    if ("reason" in read) {
      console.warn("[compose] the compose_slides result cannot start a task: %s", read.reason)
      this.push(chat.conversation.toolResult(end.id, "error", { message: read.reason }, COMPOSE_TOOL).events)
      chat.deliver(resultBlock(read.taskId, "failed", JSON.stringify(notStartedReport(read.reason))), "report")
      return
    }
    const { dispatch } = read
    if (!chat.period || chat.period.stopped) {
      console.log("[compose] task %s: dispatched after Stop; not started", dispatch.taskId)
      this.push(chat.conversation.toolResult(end.id, "error", { message: "stopped" }, COMPOSE_TOOL).events)
      const report = buildReport({
        groups: dispatch.groups.map((g) => ({ ...g, status: "cancelled", summary: "" })), outlineSlugs: dispatch.outlineSlugs,
        cancelled: true, stale: false, outputFormat: dispatch.outputFormat, deckId: dispatch.deckId,
      })
      chat.deliver(resultBlock(dispatch.taskId, "cancelled", JSON.stringify(report)), "report")
      return
    }
    const task = new ComposeTask(this, chat, end.id, dispatch)
    chat.conversation.tasks.open(end.id, dispatch.groups)
    this.push([data({ taskStart: { toolUseId: end.id, name: COMPOSE_TOOL, taskId: dispatch.taskId } })])
    task.hold()
    if (this.current) {
      console.log("[compose] task %s: waits for task %s", dispatch.taskId, this.current.dispatch.taskId)
      this.queue.push(task)
    } else this.begin(task)
  }

  private messageEnded(end: RunToolEnd, input: Record<string, unknown> | undefined, delivered: boolean): void {
    const group = Number((input as { group?: unknown } | undefined)?.group) || 0
    if (delivered) {
      this.push(this.chat.conversation.toolResult(end.id, "success", end.result, MESSAGE_TOOL).events)
      return
    }
    const running = this.current?.running() ?? []
    console.log("[compose] message_composer to group %d: not delivered", group)
    this.push(this.chat.conversation.toolResult(end.id, "error", { message: "Not delivered" }, MESSAGE_TOOL).events)
    this.chat.deliver(messageComposerError(group, running), "report")
  }

  private push(events: ChatEvent[]): void {
    for (const event of events) this.chat.push(event)
  }
}
