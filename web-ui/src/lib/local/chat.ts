// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A Local chat: one conversation on one host session (hosts.ts), with its work periods, turns,
 * steers, the Local server's own texts for the agent, Stop and its deck. The registry
 * (acp-process.ts) finds chats by id, places them on hosts and releases them.
 *
 * - **Work period.** What the SSE stream follows and what Stop ends: it starts with the first turn
 *   (`work {state: "busy"}`, the buffer numbered from 1, the SSE `id:`), lasts while a turn runs or
 *   a work hold is open (a compose task, compose-run.ts), and ends with `work {state: "idle", how}` and the
 *   `end` event (the last turn's stop reason and error, `cancelled` after Stop). The chat is busy
 *   while a period runs or a prompt is being prepared; the pool never releases a busy chat.
 * - **Turns.** `turn {id, why, text}` when one starts (`text` "" for a hidden turn), `turnEnd`
 *   when its own session/prompt is answered (in line order: no other answer and no sub-agent ends
 *   it), and a `messageStart` before the first output of every turn after the first in a period.
 *   A prompt or a steer while the period runs without a turn starts a turn in it.
 * - **Steers.** A user's message during a turn goes into it (`_session/steer`) and is reported
 *   accepted, then delivered (kiro-cli read it, or it went into a follow-up prompt of the same turn
 *   when the prompt ended before kiro-cli read it) or discarded (Stop, an exit, a failed turn).
 * - **Delivery** (`deliver`): the Local server's own text for the agent, never shown as a user
 *   message. During a turn it is a hidden steer (a follow-up prompt when kiro-cli does not take
 *   it); between turns of a period, a hidden turn; when the period is stopped, over or its kiro-cli
 *   gone, it is kept for the session's next user prompt (the registry's carry-over).
 * - **Stop** (`stop`) discards the steers, cancels the turn and every hold, and from then on
 *   nothing that can start model work is sent in that period (`maySend`); holds that do not
 *   release within STOP_SETTLE_MS are dropped and the period ends without them.
 * - **Compose.** The orchestrator's compose_slides and message_composer calls and ends go to the
 *   chat's compose runner (compose-run.ts), which answers them and holds the period while its
 *   composers run.
 * - **Decks.** A deck a tool result names gets the session's `.session` (and a fork's origin) and
 *   a new engine mark once; each turn adds its engine to the marks of the chat's decks. Each
 *   period's end writes a turn mark to the chat's decks (`.session-turn`); the next user prompt
 *   that starts a period names the deck files changed after it (`outsideChanges`, deck-changes.ts).
 */
import { randomUUID } from "crypto"
import type { EngineId } from "./acp/engine"
import type { AcpAnswer } from "./acp/transport"
import { ComposeRunner } from "./compose-run"
import { ConversationState } from "./conversation"
import { data, type BufferedEvent, type ChatEvent, type LocalEvent, type TurnHow, type TurnWhy } from "./conversation/events"
import { SteerRejectedError, steerEvent, type SteerState } from "./conversation/steer"
import { turnEnded, turnFailed, type EndEvent } from "./conversation/turn"
import { changedDeckFiles, newestDeckFileMtime } from "./deck-changes"
import { readEngineMark, readTurnMark, saveOriginToDeck, saveSessionToDeck, writeEngineMark, writeTurnMark } from "./deck-files"
import { resolveDeckDir } from "./deck-paths"
import type { HostSession, SessionSink } from "./hosts"
import { changedOutsideToken } from "./interaction-mode"
import type { SessionOrigin } from "./kiro-sessions.types"
import type { LocalSessionNoticeCode } from "./sessionNotices"
import { AgentTimeoutError } from "./turnErrors"

/** Chat events kept per work period for a reconnecting stream. */
export const MAX_BUFFERED_EVENTS = 2000
/** How long Stop waits for the work holds to release before the period ends without them (Cloud's STOP_SETTLE_S). */
export const STOP_SETTLE_MS = 5000

export type EventListener = (entry: BufferedEvent) => void

/** Work that keeps a chat's period open after its turn (a compose task). */
export interface WorkHold {
  /** Stop: cancel what the hold runs; it releases itself when its sessions answered. */
  cancel(): void
  /** Stop's settle timeout: the period ends without the hold, which emits nothing more. */
  dropped(): void
}

export interface Period {
  readonly number: number
  buffer: BufferedEvent[]
  eventId: number
  /** Stop was pressed: nothing that starts model work is sent any more. */
  stopped: boolean
  readonly holds: Set<WorkHold>
  /** A stream wrote this period's end and was not cancelled before it. */
  seen: boolean
  /** Turns started in it. */
  turns: number
  /** The last turn's end event, and how it ended. */
  lastEnd: EndEvent | null
  lastHow: TurnHow
  /** The last turn's error was already written as a data event (a hold kept the period open). */
  errorShown: boolean
  ended: boolean
}

interface Turn {
  id: string
  why: TurnWhy
  hidden: boolean
  /** JSON-RPC id of the turn's current session/prompt; only its answer ends the turn. */
  promptRequestId: number | null
  /** A messageStart goes before the turn's first output (a turn after the first of its period). */
  messageStart: boolean
}

/** What a chat asks of its registry. */
export interface ChatHooks {
  /** The origin a fork left for the first deck its chat creates (taken once). */
  takeOrigin(clientId: string): SessionOrigin | undefined
  /** Keep a text for the session's next user prompt. */
  carryOver(sessionId: string, text: string): void
  /** A work period started (its first event is pushed next). */
  periodStarted(chat: Chat): void
  /** A work period ended; its `end` was written to the listeners. */
  periodEnded(chat: Chat): void
  /** The chat's kiro-cli exited; its period has ended (not called while the chat opens). */
  hostExited(chat: Chat): void
  /** The pool needs the chat's place. */
  release(chat: Chat): void | Promise<void>
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** How a turn that was answered with `end` ended. */
function howOf(end: EndEvent): TurnHow {
  if (end.payload) return "error"
  return end.stopReason === "cancelled" ? "cancelled" : "finished"
}

export class Chat implements SessionSink {
  readonly kind = "chat" as const
  /** The chat's session; set once it is open. */
  hs!: HostSession
  readonly conversation = new ConversationState()
  readonly listeners = new Set<EventListener>()
  /** Every client id the chat is known by (`clientId` among them). */
  readonly clientIds = new Set<string>()
  /** The deck this conversation last created or was opened for. */
  deckId = ""
  /** Decks whose `.session` names this chat's session. */
  readonly savedDecks = new Set<string>()
  /** The chat belongs to a deck: an engine switch ends it once it is idle. */
  deckBound = false
  period: Period | null = null
  /** The last finished period, kept for /stream until the next one starts. */
  lastPeriod: Period | null = null
  turn: Turn | null = null
  /** A prompt is being prepared (its model change, its steer clear). */
  reserved = false
  /** The session is being opened (not placed yet: never released). */
  opening = true
  /** The registry has let the chat go. */
  released = false
  /** A `_session/steer/clear` in flight; the next prompt waits for it. */
  steerClear: Promise<void> | null = null
  /** A model change in flight; the next change and the next prompt wait for it. */
  configChange: Promise<void> | null = null
  /** The Local server's texts for the agent that wait for the end of the turn. */
  readonly pendingHarness: string[] = []
  /** Turns ended so far; a steer whose turn ended while kiro-cli queued it is taken back. */
  turnsEnded = 0
  /** The compose runner, made on the first compose_slides or message_composer call. */
  compose: ComposeRunner | null = null
  private lastActive = Date.now()
  private periods = 0
  private settleTimer: ReturnType<typeof setTimeout> | null = null
  private harnessWarned = false

  constructor(
    /** The client id the chat was created for (the fork's id for a fork); keys its pending origin. */
    public clientId: string,
    readonly agentName: string,
    readonly engine: EngineId,
    private readonly hooks: ChatHooks,
  ) {}

  /** The kiro session the chat holds (the one saved to a deck's `.session`). */
  get sessionId(): string | null {
    return this.hs?.sessionId ?? null
  }

  // ── SessionSink ──

  busy(): boolean {
    return this.opening || this.turn !== null || this.reserved || (this.period?.holds.size ?? 0) > 0
  }

  lastActivity(): number {
    return this.lastActive
  }

  release(): void | Promise<void> {
    return this.hooks.release(this)
  }

  onEvents(events: LocalEvent[]): void {
    this.compose?.observe(events)
    const { events: out, deckId, runToolUses, runToolEnds } = this.conversation.apply(events)
    if (deckId) this.saveDeck(deckId)
    if (this.period) {
      for (const event of out) {
        if (this.turn?.messageStart && !(event.kind === "data" && "steer" in event.payload)) {
          this.turn.messageStart = false
          this.push(data({ event: { messageStart: { role: "assistant" } } }))
        }
        this.push(event)
      }
    }
    if (!runToolUses.length && !runToolEnds.length) return
    this.compose ??= new ComposeRunner(this)
    for (const use of runToolUses) this.compose.toolUse(use)
    for (const end of runToolEnds) this.compose.toolEnded(end)
  }

  /** The kiro-cli is gone: a running turn ends with agent_exited and the period at once. */
  onHostExit(code: number | null): void {
    console.log("[acp close] sessionId=%s code=%s", this.sessionId, code)
    const period = this.period
    if (period) {
      for (const hold of [...period.holds]) hold.cancel()
      period.holds.clear()
      this.clearSettleTimer()
    }
    if (this.turn) this.finishTurn("error", turnFailed({ code: "agent_exited", message: `kiro-cli exited with code ${code}` }))
    else this.maybeEndPeriod()
    for (const text of this.pendingHarness.splice(0)) this.keepForLater(text)
    // An opening chat is not registered yet: its failed open drops the session and reports the exit.
    if (!this.opening) this.hooks.hostExited(this)
  }

  // ── Period and turns ──

  touch(): void {
    this.lastActive = Date.now()
  }

  subscribe(fn: EventListener): () => void {
    this.listeners.add(fn)
    return () => { this.listeners.delete(fn) }
  }

  /** Nothing that starts model work may be sent: Stop was pressed in this period. */
  maySend(): boolean {
    return !this.period?.stopped
  }

  /** Number a chat event within the period, buffer it for reconnects and hand it to every listener. */
  push(event: ChatEvent): void {
    const period = this.period
    if (!period) return
    const entry: BufferedEvent = { id: ++period.eventId, event }
    period.buffer.push(entry)
    if (period.buffer.length > MAX_BUFFERED_EVENTS) period.buffer.shift()
    for (const fn of [...this.listeners]) fn(entry)
  }

  /**
   * A user prompt starts a turn: in a new period when none runs, else in the running one (a hold
   * keeps it open). Returns the id the invoke stream replays from: 1 for a new period (its
   * `work` event first), else the turn's first event (the earlier turns are not this reply's).
   */
  beginPrompt(displayText: string, notice?: LocalSessionNoticeCode): number {
    const fresh = !this.period
    if (fresh) this.beginPeriod()
    const turnStart = this.beginTurn("prompt", displayText, false)
    const first = fresh ? 1 : turnStart
    if (this.deckBound) {
      for (const deckId of this.savedDecks) {
        const mark = readEngineMark(deckId)
        writeEngineMark(deckId, { last: this.engine, engines: mark.engines.includes(this.engine) ? mark.engines : [...mark.engines, this.engine] })
      }
    }
    if (notice) this.push(data({ notice: { code: notice } }))
    return first
  }

  /** Send session/prompt for the turn; its answer ends the turn. After Stop, the turn ends cancelled instead. */
  startPrompt(text: string): void {
    const turn = this.turn
    if (!turn) return
    if (!this.maySend()) {
      this.finishTurn("cancelled", turnEnded("cancelled"))
      return
    }
    const id: number = this.hs.prompt(text, (answer) => {
      if (this.turn === turn && turn.promptRequestId === id) this.promptAnswered(answer)
    })
    turn.promptRequestId = id
  }

  /** Keep work going after the turn: the period ends when every hold released. Throws without a period. */
  hold(work: WorkHold): () => void {
    const period = this.period
    if (!period) throw new Error("no work period to hold")
    period.holds.add(work)
    let released = false
    return () => {
      if (released) return
      released = true
      if (period.holds.delete(work) && this.period === period) this.maybeEndPeriod()
    }
  }

  /** Hand the Local server's text to the agent (see the header); returns where it went. */
  deliver(text: string, why: "wake" | "report"): "turn" | "steer" | "later" {
    const period = this.period
    if (!period || period.stopped || this.released || this.hs.host.exited) {
      this.keepForLater(text)
      return "later"
    }
    if (this.turn) {
      void this.harnessSteer(text, why)
      return "steer"
    }
    this.beginTurn(why, "", true)
    this.startPrompt(text)
    return "turn"
  }

  /**
   * A user message: into the running turn (`_session/steer`); with a hold and no turn, a turn of
   * its own at once (accepted, the turn, delivered). Resolves once it is accepted; throws
   * SteerRejectedError when no period runs (or it was stopped), or kiro-cli did not queue it.
   */
  async steer(id: string, text: string): Promise<void> {
    const period = this.period
    if (!period || period.stopped || (!this.turn && this.reserved)) throw new SteerRejectedError("session_idle")
    if (!this.turn) {
      this.pushSteer({ id, text, state: "accepted" })
      this.beginTurn("steer", text, false)
      this.pushSteer({ id, state: "delivered" })
      this.startPrompt(text)
      return
    }
    const caps = this.hs.host.caps
    if (caps && !caps.steer) throw new SteerRejectedError("steer_not_queued", "kiro-cli does not support steering")
    const turns = this.turnsEnded
    let result: { queued?: boolean; messageId?: string; dropped?: string }
    try {
      result = await this.hs.steer(text)
    } catch (error) {
      if (error instanceof AgentTimeoutError) throw error
      throw new SteerRejectedError("steer_not_queued", errorText(error))
    }
    // V3 drops a steer that raced the end of the turn (`dropped: "epoch_changed"`).
    if (result.queued !== true) throw new SteerRejectedError("steer_not_queued", result.dropped)
    if (this.turnsEnded !== turns) {
      this.clearSteerQueue()
      throw new SteerRejectedError("session_idle")
    }
    this.conversation.steers.add({ id, text, ...(result.messageId ? { messageId: result.messageId } : {}) })
    this.touch()
    this.pushSteer({ id, text, state: "accepted" })
  }

  /** Stop the period (see the header). */
  stop(): void {
    const period = this.period
    if (!period) return
    if (!period.stopped) {
      period.stopped = true
      for (const text of this.pendingHarness.splice(0)) this.keepForLater(text)
      this.discardSteers()
    }
    if (this.turn) this.hs.cancel()
    for (const hold of [...period.holds]) hold.cancel()
    if (period.holds.size && !this.settleTimer) this.settleTimer = setTimeout(() => this.settle(period), STOP_SETTLE_MS)
    this.maybeEndPeriod()
  }

  /** A deck the chat was opened for: its next turns mark the deck, and an engine switch ends the chat once idle. */
  bindDeck(deckId: string): void {
    this.deckId = deckId
    this.savedDecks.add(deckId)
    this.deckBound = true
  }

  /**
   * For a user prompt that starts a period: the deck files changed outside the chat since its
   * last period ended, one `Changed outside since your last turn:` block per deck, or null (a
   * period runs, no deck's turn mark is this session's, nothing changed).
   */
  outsideChanges(): string | null {
    const sessionId = this.sessionId
    if (this.period || !sessionId) return null
    const blocks: string[] = []
    for (const deckId of this.savedDecks) {
      const mark = readTurnMark(deckId)
      if (!mark || mark.sessionId !== sessionId) continue
      const dir = resolveDeckDir(deckId)
      if (!dir) continue
      const { files, more } = changedDeckFiles(dir, mark.endedAt)
      if (!files.length) continue
      console.log("[acp] sessionId=%s: deck %s changed outside since the last turn (%d files)", sessionId, deckId, files.length + more)
      blocks.push(changedOutsideToken(dir, files, more))
    }
    return blocks.length ? blocks.join("\n\n") : null
  }

  /** The period ended: each deck of the chat gets a turn mark no earlier than its newest file. */
  private markTurnEnd(): void {
    const sessionId = this.sessionId
    if (!sessionId) return
    for (const deckId of this.savedDecks) {
      const dir = resolveDeckDir(deckId)
      if (!dir) continue
      writeTurnMark(deckId, { sessionId, endedAt: Math.max(Date.now(), newestDeckFileMtime(dir)) })
    }
  }

  private beginPeriod(): void {
    this.period = {
      number: ++this.periods, buffer: [], eventId: 0, stopped: false, holds: new Set(), seen: false,
      turns: 0, lastEnd: null, lastHow: "finished", errorShown: false, ended: false,
    }
    this.lastPeriod = null
    this.hooks.periodStarted(this)
    this.push(data({ work: { state: "busy" } }))
  }

  /** Start a turn in the running period; returns the id of its first event. */
  private beginTurn(why: TurnWhy, text: string, hidden: boolean): number {
    const period = this.period!
    const turn: Turn = { id: randomUUID(), why, hidden, promptRequestId: null, messageStart: period.turns > 0 }
    period.turns++
    this.turn = turn
    this.hs.engine.beginTurn()
    this.conversation.beginTurn()
    const first = period.eventId + 1
    this.push(data({ turn: { id: turn.id, why, text: hidden ? "" : text } }))
    this.touch()
    return first
  }

  /**
   * Only the answer to this turn's session/prompt ends the turn (kiro-cli sends no turn end for
   * sub-agent sessions); an error answer to any other request (a steer, a model change) rejects
   * that request alone. It is handled in line order, before the lines that follow it.
   */
  private promptAnswered(answer: AcpAnswer): void {
    if (!answer.ok) {
      this.finishTurn("error", turnFailed({ message: answer.error.message }))
      return
    }
    const stopReason = (answer.result as { stopReason?: string } | undefined)?.stopReason ?? "end_turn"
    if (stopReason === "end_turn" && (this.conversation.steers.size || this.pendingHarness.length) && this.maySend()) {
      void this.continueWithSteers()
      return
    }
    const end = turnEnded(stopReason)
    this.finishTurn(howOf(end), end)
  }

  /**
   * The prompt ended (end_turn) before kiro-cli read these steers. As in Cloud, they are not
   * dropped: they are taken out of kiro-cli's queue (left there, kiro-cli would put them into the
   * user's next message) and sent as a follow-up prompt on the same turn and stream, the user's
   * first, then the Local server's own texts. A steer queued after the clear is read by kiro-cli in
   * that prompt itself. A Stop or an exit meanwhile ends the turn instead, and a clear that fails
   * ends it with the steers discarded.
   */
  private async continueWithSteers(): Promise<void> {
    const turn = this.turn!
    turn.promptRequestId = null
    const taken = this.conversation.steers.peek()
    let cleared = true
    if (taken.length) {
      try {
        await this.hs.clearSteers()
      } catch (error) {
        console.warn("[acp] _session/steer/clear: %s", errorText(error))
        cleared = false
      }
    }
    if (this.hs.host.exited || this.turn !== turn) return
    if (!cleared || !this.maySend()) {
      const end = turnEnded(cleared ? "cancelled" : "end_turn")
      this.finishTurn(howOf(end), end)
      return
    }
    this.conversation.steers.remove(taken)
    const user = taken.filter((steer) => !steer.hidden)
    const harness = [...taken.filter((steer) => steer.hidden).map((steer) => steer.text), ...this.pendingHarness.splice(0)]
    console.log("[acp] sessionId=%s: prompt ended before %d steer(s) were read; sending them as a follow-up prompt", this.sessionId, user.length + harness.length)
    for (const steer of user) this.pushSteer({ id: steer.id, state: "delivered" })
    this.startPrompt([...user.map((steer) => steer.text), ...harness].join("\n\n"))
  }

  /** The turn is over: close what it left open (steers, a Compose card), report it, and end the period if nothing holds it. */
  private finishTurn(how: TurnHow, end: EndEvent): void {
    const turn = this.turn
    const period = this.period
    if (!turn || !period) return
    this.turn = null
    this.turnsEnded++
    this.hs.engine.endTurn()
    this.discardSteers()
    for (const text of this.pendingHarness.splice(0)) this.keepForLater(text)
    for (const event of this.conversation.endTurn()) this.push(event)
    this.push(data({ turnEnd: { id: turn.id, how } }))
    period.lastEnd = end
    period.lastHow = how
    period.errorShown = false
    // The period goes on (a hold): the turn's error is shown now, not with the period's end.
    if (period.holds.size > 0 && end.payload) {
      this.push(data(end.payload))
      period.errorShown = true
    }
    this.maybeEndPeriod()
  }

  /** No turn runs and nothing holds the period: it ends (`work idle`, then `end`). */
  private maybeEndPeriod(): void {
    const period = this.period
    if (!period || this.turn || period.holds.size) return
    this.clearSettleTimer()
    const how: TurnHow = period.stopped ? "cancelled" : period.lastHow
    this.push(data({ work: { state: "idle", how } }))
    const last = period.lastEnd ?? turnEnded("end_turn")
    let end: ChatEvent = last
    if (period.stopped && (!last.payload || last.stopReason === "cancelled")) end = turnEnded("cancelled")
    else if (period.errorShown) end = { kind: "end", ...(last.stopReason ? { stopReason: last.stopReason } : {}) }
    period.ended = true
    this.push(end)
    this.period = null
    this.lastPeriod = period
    this.markTurnEnd()
    this.hooks.periodEnded(this)
  }

  /** Stop's settle timeout: the holds still open are dropped, and the period ends without them. */
  private settle(period: Period): void {
    this.settleTimer = null
    if (this.period !== period) return
    for (const hold of [...period.holds]) {
      console.warn("[acp] sessionId=%s: work did not stop within %dms after Stop; ending the period without it", this.sessionId, STOP_SETTLE_MS)
      hold.dropped()
      period.holds.delete(hold)
    }
    this.maybeEndPeriod()
  }

  private clearSettleTimer(): void {
    if (this.settleTimer) clearTimeout(this.settleTimer)
    this.settleTimer = null
  }

  /** A text for the agent that cannot be delivered now: kept for the session's next user prompt. */
  private keepForLater(text: string): void {
    if (this.sessionId) this.hooks.carryOver(this.sessionId, text)
  }

  /** The Local server's text into the running turn; one kiro-cli does not take waits for the turn's end. */
  private async harnessSteer(text: string, why: "wake" | "report"): Promise<void> {
    if (!this.maySend()) {
      this.keepForLater(text)
      return
    }
    const turns = this.turnsEnded
    let result: { queued?: boolean; messageId?: string; dropped?: string }
    try {
      result = await this.hs.steer(text)
    } catch (error) {
      result = { queued: false, dropped: errorText(error) }
    }
    const sameTurn = this.turn !== null && this.turnsEnded === turns
    if (result.queued === true && sameTurn) {
      this.conversation.steers.add({ id: randomUUID(), text, hidden: true, ...(result.messageId ? { messageId: result.messageId } : {}) })
      return
    }
    // The turn ended while kiro-cli queued it: take it back out of kiro-cli's queue.
    if (result.queued === true) this.clearSteerQueue()
    else if (!this.harnessWarned) {
      this.harnessWarned = true
      console.warn("[acp] sessionId=%s: kiro-cli did not take a text for the agent during the turn (%s); it follows at the turn's end", this.sessionId, result.dropped ?? "not queued")
    }
    if (sameTurn) this.pendingHarness.push(text)
    else this.deliver(text, why)
  }

  /** Tell the listeners (and a reconnecting stream) where a steer is now. */
  private pushSteer(steer: { id: string; text?: string; state: SteerState }): void {
    this.push(steerEvent(steer))
  }

  /**
   * Take what kiro-cli still queues for this session out of its queue. Left there, V2 and V3 both
   * put it into the next prompt, after a Stop and (V2) after a normal end.
   */
  private clearSteerQueue(): void {
    if (this.hs.host.exited) return
    const cleared = this.hs.clearSteers().then(() => undefined, (error: Error) => { console.warn("[acp] _session/steer/clear: %s", error.message) })
    const done = cleared.finally(() => { if (this.steerClear === done) this.steerClear = null })
    this.steerClear = done
  }

  /** The turn ended before kiro-cli read these steers: clear them; the user's are reported not delivered, the Local server's kept for later. */
  private discardSteers(): void {
    const left = this.conversation.steers.takeAll()
    if (!left.length) return
    this.clearSteerQueue()
    for (const steer of left) {
      if (steer.hidden) this.keepForLater(steer.text)
      else this.pushSteer({ id: steer.id, state: "discarded" })
    }
  }

  /**
   * A tool result named a deck: write the session to its `.session` once (and a new engine mark),
   * and the fork's origin to the first deck the conversation creates.
   */
  private saveDeck(deckId: string): void {
    if (this.savedDecks.has(deckId) || !this.sessionId) return
    if (!saveSessionToDeck(deckId, this.sessionId)) return
    writeEngineMark(deckId, { last: this.engine, engines: [this.engine] })
    this.bindDeck(deckId)
    const origin = this.hooks.takeOrigin(this.clientId)
    if (origin) saveOriginToDeck(deckId, origin)
  }
}
