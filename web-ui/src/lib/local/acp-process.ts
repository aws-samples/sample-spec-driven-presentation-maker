// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Local chat registry: the API the routes use to reach chats (chat.ts), which run on the
 * kiro-cli processes of the host pool (hosts.ts), one kiro-cli per chat. Switching decks does not
 * interrupt a running chat.
 *
 * - **Ids.** `aliases` holds every id a client may use for a chat: its client ids (the invoke's
 *   `sessionId`, a deck's fallback id, a fork's id) and its current kiro session id (the one saved
 *   to a deck's `.session`). A chat for a kiro session is found by either before anything is
 *   opened, so a kiro session is open in at most one chat (a second tab or a reopened deck reuses
 *   it). `register` is the only writer, `releaseChat` the only remover.
 * - **Placement.** A new chat, a reopened deck, a fork: the pool starts a kiro-cli of the configured
 *   engine for it (`acquireForChat`) and the chat opens its session there. An open that fails reports
 *   AgentStartError, AgentTimeoutError or SessionLockedError (a session another kiro-cli outside
 *   this server holds), and registers nothing.
 * - **Release.** `releaseChat` is the one way out: the chat's ids are forgotten and its kiro-cli
 *   is killed. The pool releases the least recently active idle chat for its cap; an engine switch
 *   releases idle deck-bound chats of the other engine (a busy one when its period ends); a
 *   kiro-cli that opened composer sessions it cannot close ends once its chat is idle. A busy chat
 *   is never released. A
 *   chat that is released, or whose kiro-cli exited, is remembered as an orphan: the next message
 *   of its client id opens its kiro session again.
 * - **Carry-over.** Texts for the agent a chat could not deliver (after Stop, after an exit) wait
 *   under the kiro session and go before the user's text of its next prompt.
 * - **Stop during start.** A start (an invoke opening its chat and sending its prompt) registers
 *   under its client id (`beginStart`) before anything is opened, so Stop (`cancelSession`, also a
 *   POST from another tab) aborts it: the pool kills the starting kiro-cli, and no prompt is sent.
 * - **Unseen periods.** A work period whose end no stream wrote (its tab was closed) is replayed
 *   once by `/api/agent/stream` (`openStream`), also after its chat was released: `releaseChat`
 *   keeps it under every id of the chat (at most MAX_UNSEEN_PERIODS). It counts as seen once a
 *   stream wrote its end and was not cancelled before; the chat's next period drops it.
 * - **Decks.** `.session`, `.session-engine` and a fork's origin are the chat's (chat.ts,
 *   deck-files.ts); a deck reopened on the other engine says so (`otherEngine`).
 * - **Forks** (`forkSession`): the fork is made and opened with the engine's session; a fork
 *   kiro-cli could not read, or an open that fails or is cancelled once the fork exists, is deleted
 *   through that session (`discardFork`), never anything else.
 * - **Listing** the stored sessions (`withEngineConnection`) uses a live kiro-cli of the engine,
 *   else the pool starts one for the listing.
 * - **Models.** Each chat chooses its kiro session's model and effort (`chooseSessionModel`). An
 *   idle chat changes them at once (the engine's setModel, one change at a time); otherwise the
 *   choice waits under the chat's client id and is applied right before its next session/prompt,
 *   so a turn never switches models half-way. The models are listed without starting kiro-cli:
 *   from the chat's session, else the last list a session of the configured engine reported
 *   (kept in acp-models.json, acp/model-cache.ts).
 */
import { DECK_ROOT } from "./deck-paths"
import type { EngineCapabilities, EngineId, LoadOutcome, ModelChoice, ModelOption, StoreContext } from "./acp/engine"
import { readEngineConfig } from "./acp/engine-config"
import { readModelCache, writeModelCache } from "./acp/model-cache"
import { Chat, type ChatHooks, type EventListener, type Period } from "./chat"
import type { BufferedEvent } from "./conversation/events"
import { SteerRejectedError } from "./conversation/steer"
import { readEngineMark, saveSessionToDeck, writeEngineMark } from "./deck-files"
import { discardFork, HostOpenError, pool, type Open, type OpenPhase } from "./hosts"
import type { SessionOrigin } from "./kiro-sessions.types"
import { ForkNotReadError, ModelChoiceError, SessionBusyError, SessionLockedError } from "./sessionErrors"
import type { LocalSessionNoticeCode } from "./sessionNotices"

export { DECK_ROOT }
export type { LoadOutcome, ModelChoice, ModelOption }
export {
  readChatFromDeck, readEngineMark, readOriginFromDeck, readSessionFromDeck, saveChatToDeck, saveOriginToDeck, saveSessionToDeck,
  writeEngineMark, type EngineMark,
} from "./deck-files"

/** Model choices kept for chats that are not idle; the oldest is dropped beyond this. */
const MAX_PENDING_MODEL_CHOICES = 100
/** Released chats whose next message opens their kiro session again. */
const MAX_ORPHANS = 100
/** Sessions with texts kept for their next prompt, and texts per session. */
const MAX_CARRY_OVER_SESSIONS = 100
const MAX_CARRY_OVER_TEXTS = 5

/** Every id of a chat (`register`). */
const aliases = new Map<string, Chat>()
export const pendingOrigins = new Map<string, SessionOrigin>()
/** Client id → the kiro session of its chat, released or left by an exited kiro-cli. */
const orphans = new Map<string, string>()
/** Kiro session id → texts for the agent its next user prompt starts with. */
const carryOver = new Map<string, string[]>()
/** Finished periods of released chats that no stream delivered, oldest first, with the ids they are kept under. */
const MAX_UNSEEN_PERIODS = 50
const unseen = new Map<Period, Set<string>>()
const unseenById = new Map<string, Period>()
/** Client id → the starts in progress for it (`beginStart`), which Stop aborts. */
const pendingStarts = new Map<string, Set<AbortController>>()

/** The model list a session of each engine last reported in this server (also in acp-models.json). */
const knownModels = new Map<EngineId, ModelOption[]>()
/** Client id → the model choice its chat made while it could not take it at once. */
const pendingModelChoices = new Map<string, ModelChoice>()

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))
const throwIfAborted = (signal: AbortSignal | undefined) => {
  if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError")
}

/** Map insertion order as LRU: (re)insert `key` last and drop the oldest beyond `max`. */
function keepNewest<V>(map: Map<string, V>, key: string, value: V, max: number): void {
  map.delete(key)
  map.set(key, value)
  while (map.size > max) map.delete(map.keys().next().value!)
}

const hooks: ChatHooks = {
  takeOrigin(clientId) {
    const origin = pendingOrigins.get(clientId)
    if (origin) pendingOrigins.delete(clientId)
    return origin
  },
  carryOver(sessionId, text) {
    const texts = [...(carryOver.get(sessionId) ?? []), text].slice(-MAX_CARRY_OVER_TEXTS)
    keepNewest(carryOver, sessionId, texts, MAX_CARRY_OVER_SESSIONS)
  },
  periodStarted(chat) {
    // The chat has moved on: what an earlier period of its ids left is not replayed any more.
    for (const id of idsOf(chat)) forgetUnseen(id)
  },
  periodEnded(chat) { onPeriodEnd(chat) },
  hostExited(chat) { releaseChat(chat, { remember: true }) },
  release(chat) { releaseChat(chat, { remember: true }) },
}

/** Every id a chat is known by. */
function idsOf(chat: Chat): string[] {
  return [...chat.clientIds, ...(chat.sessionId ? [chat.sessionId] : [])]
}

/** Keep a finished period no stream delivered under `ids`; the oldest goes beyond MAX_UNSEEN_PERIODS. */
function keepUnseen(period: Period, ids: string[]): void {
  if (period.seen) return
  const keys = unseen.get(period) ?? new Set<string>()
  for (const id of ids) {
    const earlier = unseenById.get(id)
    if (earlier && earlier !== period) forgetUnseen(id)
    keys.add(id)
    unseenById.set(id, period)
  }
  unseen.set(period, keys)
  while (unseen.size > MAX_UNSEEN_PERIODS) {
    const [oldest, oldestKeys] = unseen.entries().next().value!
    unseen.delete(oldest)
    for (const id of oldestKeys) if (unseenById.get(id) === oldest) unseenById.delete(id)
  }
}

function forgetUnseen(id: string): void {
  const period = unseenById.get(id)
  if (!period) return
  unseenById.delete(id)
  const keys = unseen.get(period)
  keys?.delete(id)
  if (keys && !keys.size) unseen.delete(period)
}

/** A stream wrote the period's end: it is delivered, and is not replayed again. */
function markSeen(period: Period): void {
  period.seen = true
  for (const id of unseen.get(period) ?? []) if (unseenById.get(id) === period) unseenById.delete(id)
  unseen.delete(period)
}

/** The chats (each once). */
function chats(): Chat[] {
  return [...new Set(aliases.values())]
}

/** The only writer of `aliases`: the chat under every client id that uses it and its kiro session id. */
function register(chat: Chat, clientId: string): void {
  chat.clientIds.add(clientId)
  for (const id of chat.clientIds) aliases.set(id, chat)
  if (chat.sessionId) aliases.set(chat.sessionId, chat)
  orphans.delete(clientId)
  chat.touch()
}

/**
 * The only way out of the registry: forget every id of the chat and its pending origin, and kill
 * its kiro-cli. `remember`: its client ids reopen its kiro session on their next message.
 */
function releaseChat(chat: Chat, opts: { remember: boolean }): void {
  if (chat.released) return
  chat.released = true
  if (opts.remember && chat.sessionId) {
    for (const id of chat.clientIds) keepNewest(orphans, id, chat.sessionId, MAX_ORPHANS)
  }
  if (chat.lastPeriod && !chat.lastPeriod.seen) keepUnseen(chat.lastPeriod, idsOf(chat))
  for (const [id, candidate] of aliases) if (candidate === chat) aliases.delete(id)
  pendingOrigins.delete(chat.clientId)
  endHost(chat)
}

/** A chat whose fork is deleted: forgotten, and its kiro-cli killed. */
function dropChat(chat: Chat): void {
  chat.released = true
  for (const [id, candidate] of aliases) if (candidate === chat) aliases.delete(id)
  pendingOrigins.delete(chat.clientId)
  endHost(chat)
}

function endHost(chat: Chat): void {
  const host = chat.hs.host
  chat.hs.drop()
  if (!host.exited) host.kill()
}

/** The release checks once a period's end was written to its listeners. */
function onPeriodEnd(chat: Chat): void {
  if (chat.released) return
  const host = chat.hs.host
  if (host.exited) return
  // Settings switched the engine while this period ran: the deck's next message opens it on the new one.
  if (chat.deckBound && chat.engine !== readEngineConfig().engine) {
    console.log("[acp] sessionId=%s: the agent engine is no longer %s; ending the deck's chat", chat.sessionId, chat.engine)
    releaseChat(chat, { remember: true })
    return
  }
  // A kiro-cli that cannot close sessions keeps the composer sessions it opened: end it once idle.
  if (!host.canClose() && host.auxOpened > 0 && !chat.busy()) {
    console.log("[acp] sessionId=%s: ending its kiro-cli, which holds composer sessions it cannot close", chat.sessionId)
    releaseChat(chat, { remember: true })
  }
}

/** The chat a client id, or the kiro session it opens, already has; registered under the client id. */
function findLive(clientId: string, sessionId: string | null): Chat | null {
  const chat = aliases.get(clientId) ?? (sessionId ? (aliases.get(sessionId) ?? chats().find((c) => c.sessionId === sessionId)) : undefined)
  if (!chat) return null
  register(chat, clientId)
  return chat
}

/** Place a chat on a host of the configured engine and open its session (`how`). Not registered yet. */
async function openChat(
  clientId: string,
  agentName: string,
  how: Open,
  opts: { signal?: AbortSignal; onPhase?: OpenPhase } = {},
): Promise<{ chat: Chat; outcome: LoadOutcome }> {
  if (opts.signal?.aborted) throw new DOMException("Request cancelled", "AbortError")
  opts.onPhase?.("starting")
  const engine = readEngineConfig().engine
  const host = await pool.acquireForChat(engine, agentName, { signal: opts.signal })
  const chat = new Chat(clientId, agentName, engine, hooks)
  let opened: Awaited<ReturnType<typeof host.openSession>>
  try {
    opened = await host.openSession(agentName, how, { signal: opts.signal, onPhase: opts.onPhase, sink: chat })
  } catch (error) {
    if (error instanceof HostOpenError && error.kind === "session_locked") throw new SessionLockedError(error.message)
    throw error
  }
  chat.hs = opened.hs
  chat.opening = false
  if (!chat.clientId) chat.clientId = opened.hs.sessionId!
  rememberModels(chat)
  return { chat, outcome: opened.outcome }
}

/**
 * Run `fn` with a lazy connection to an initialized kiro-cli of `engine`: a live one, else one
 * the pool starts on the first `connect` (kept when it can carry chats, else killed once `fn` is
 * done). Concurrent listings are shared by the session catalog, not here.
 */
export async function withEngineConnection<T>(engine: EngineId, fn: (connect: StoreContext["connect"]) => Promise<T>): Promise<T> {
  let acquired: ReturnType<typeof pool.acquireForListing> | undefined
  const connect: StoreContext["connect"] = async () => {
    acquired ??= pool.acquireForListing(engine)
    const { request, caps } = await acquired
    return { request, caps }
  }
  try {
    return await fn(connect)
  } finally {
    void acquired?.then(({ release }) => release(), () => {})
  }
}

// ── Public API ──

/**
 * A start for `clientId` (opening its chat, preparing its prompt): its `signal` follows `outer`
 * (the request) and Stop for the client id (`cancelSession`, `cancelAll`). `stoppedByUser` tells
 * Stop from a client that went away; `end` once the prompt's period started (or the start failed).
 */
export function beginStart(clientId: string, outer?: AbortSignal): { signal: AbortSignal; stoppedByUser: () => boolean; end: () => void } {
  const controller = new AbortController()
  let stopped = false
  const follow = () => controller.abort()
  if (outer?.aborted) controller.abort()
  else outer?.addEventListener("abort", follow, { once: true })
  const starts = pendingStarts.get(clientId) ?? new Set<AbortController>()
  starts.add(controller)
  pendingStarts.set(clientId, starts)
  controller.signal.addEventListener("abort", () => { if (!outer?.aborted) stopped = true }, { once: true })
  return {
    signal: controller.signal,
    stoppedByUser: () => stopped,
    end: () => {
      outer?.removeEventListener("abort", follow)
      starts.delete(controller)
      if (!starts.size && pendingStarts.get(clientId) === starts) pendingStarts.delete(clientId)
    },
  }
}

/** Abort the starts in progress for a client id (all of them without one). */
function abortStarts(clientId?: string): void {
  const groups = clientId ? [pendingStarts.get(clientId)] : [...pendingStarts.values()]
  for (const starts of groups) for (const controller of starts ?? []) controller.abort()
}

/** Whether a chat is known by this id (a client id or its kiro session id). */
export function hasProcess(sessionId: string): boolean {
  return aliases.has(sessionId)
}

/** Release a chat and every id of it (its kiro-cli too when it carries only this chat). */
export function terminateProcess(sessionId: string): void {
  const chat = aliases.get(sessionId) ?? chats().find((candidate) => candidate.sessionId === sessionId)
  if (chat) releaseChat(chat, { remember: false })
}

/**
 * A Settings switch to `engine`: the idle deck-bound chats of other engines are released now (the
 * deck's next message opens its session on `engine`); a busy one is released when its period ends.
 */
export function terminateIdleProcesses(engine: EngineId): void {
  for (const chat of chats()) {
    if (chat.engine === engine || !chat.deckBound || chat.busy()) continue
    console.log("[acp] sessionId=%s: the agent engine is now %s; ending the deck's %s chat", chat.sessionId, engine, chat.engine)
    releaseChat(chat, { remember: true })
  }
}

/** What the kiro-cli of a chat advertised (null without a chat). */
export function getCapabilities(sessionId: string): EngineCapabilities | null {
  return aliases.get(sessionId)?.hs.host.caps ?? null
}

/**
 * A chat for a client id that has none: a new session, or, for a client whose chat was released
 * or whose kiro-cli exited (an orphan), its kiro session opened again (`resumed`; `notice` when
 * kiro-cli did not have it any more and the chat starts empty).
 */
export async function createNewProcessFor(
  clientId: string,
  agentName: string = "sdpm-orchestrator",
  opts: { signal?: AbortSignal } = {},
): Promise<{ chat: Chat; resumed: boolean; notice?: LocalSessionNoticeCode }> {
  const orphan = orphans.get(clientId) ?? null
  if (orphan) {
    const live = findLive(clientId, orphan)
    if (live) return { chat: live, resumed: true }
  }
  const { chat, outcome } = await openChat(clientId, agentName, orphan ? { kind: "load", sessionId: orphan } : { kind: "new" }, opts)
  register(chat, clientId)
  if (!orphan) return { chat, resumed: false }
  if (outcome === "created") return { chat, resumed: false, notice: "context_not_carried_over" }
  return { chat, resumed: true }
}

/**
 * The chat of a reopened deck, registered under `clientId`: the live chat of the client or of the
 * deck's saved session (`resumed`), else the saved session opened on the configured engine (its
 * engine tells `resumed` from `created`), or a new one when the deck has none (`created`). The
 * chat is bound to the deck either way. A created session is saved to `.session` with a new
 * engine mark; a resumed one reports `otherEngine` when its turns also ran on the other engine.
 */
export async function openDeckSession(
  clientId: string,
  deckId: string,
  savedSessionId: string | null,
  agentName: string,
  opts: { signal?: AbortSignal } = {},
): Promise<{ chat: Chat; outcome: LoadOutcome; otherEngine: boolean }> {
  let chat = findLive(clientId, savedSessionId)
  let outcome: LoadOutcome = "resumed"
  if (!chat) {
    const opened = await openChat(clientId, agentName, savedSessionId ? { kind: "load", sessionId: savedSessionId } : { kind: "new" }, opts)
    chat = opened.chat
    outcome = opened.outcome
    register(chat, clientId)
  }
  chat.bindDeck(deckId)
  if (outcome === "created") {
    saveSessionToDeck(deckId, chat.sessionId!)
    writeEngineMark(deckId, { last: chat.engine, engines: [chat.engine] })
    return { chat, outcome, otherEngine: false }
  }
  const mark = readEngineMark(deckId)
  return { chat, outcome, otherEngine: mark.last !== chat.engine && mark.engines.includes(chat.engine) }
}

/**
 * Fork a stored session (`sourceId`, any store the configured engine can open) and open the
 * fork, registered under the fork's id (its client id too, which keys `pendingOrigins`). A fork
 * kiro-cli could not read is deleted again: ForkNotReadError.
 */
export async function forkSession(
  sourceId: string,
  agentName: string,
  opts: { signal?: AbortSignal; onPhase?: OpenPhase } = {},
): Promise<{ chat: Chat; sessionId: string; outcome: LoadOutcome }> {
  const { chat, outcome } = await openChat("", agentName, { kind: "fork", sourceId }, opts)
  const sessionId = chat.sessionId!
  if (outcome === "created") {
    console.warn("[acp] fork %s of %s: kiro-cli could not read it", sessionId, sourceId)
    await discardFork(chat.hs.engine, sessionId)
    dropChat(chat)
    throw new ForkNotReadError()
  }
  register(chat, sessionId)
  return { chat, sessionId, outcome }
}

/** Delete a fork `forkSession` made and release its chat (a fork that is not live is left alone). */
export async function discardForkedSession(sessionId: string): Promise<void> {
  const chat = aliases.get(sessionId)
  if (!chat || chat.sessionId !== sessionId) return
  for (const [id, candidate] of aliases) if (candidate === chat) aliases.delete(id)
  await discardFork(chat.hs.engine, sessionId)
  dropChat(chat)
}

/**
 * The chat of a forked chat: `clientId` is the fork's id, which is also the forked kiro
 * session's. The live chat, or the fork opened again (`created` when kiro-cli could not read it
 * and started an empty session).
 */
export async function openForkedSession(
  clientId: string,
  agentName: string,
  opts: { signal?: AbortSignal; onPhase?: OpenPhase } = {},
): Promise<{ chat: Chat; outcome: LoadOutcome }> {
  const live = findLive(clientId, null)
  if (live) return { chat: live, outcome: "resumed" }
  const { chat, outcome } = await openChat(clientId, agentName, { kind: "load", sessionId: clientId }, opts)
  register(chat, clientId)
  return { chat, outcome }
}

/**
 * Send a user prompt to a chat. Its turn starts a work period when none runs, else it is a turn
 * of the running one (a hold keeps it open); `replayFrom` is the id of the turn's first event
 * (the period's events are numbered from 1), and a `notice` about the chat's session
 * (sessionNotices.ts) follows the `turn` event. `displayText` is what the `turn` event shows (the
 * user's own text). The chat's pending model choice is applied first (one kiro-cli refuses is
 * logged and the prompt goes on), then the texts kept for the session go before `text`.
 * Throws SessionBusyError while the chat's turn runs or its stopped period settles (the same chat
 * open in two panels or tabs); prompts are not queued. Throws AbortError when `signal` (the
 * start's, `beginStart`) aborts before the turn started.
 */
export async function sendPrompt(
  sessionId: string,
  text: string,
  opts: { notice?: LocalSessionNoticeCode; displayText?: string; signal?: AbortSignal } = {},
): Promise<{ sessionId: string; replayFrom: number; subscribe: (fn: EventListener) => () => void; send: () => void; onEnd: () => void }> {
  const chat = aliases.get(sessionId)
  if (!chat) throw new Error(`no chat for session ${sessionId}`)
  throwIfAborted(opts.signal)
  // Steers the last turn left must be out of kiro-cli's queue before this prompt.
  if (chat.steerClear) await chat.steerClear
  throwIfAborted(opts.signal)
  if (chat.turn || chat.reserved || chat.period?.stopped) throw new SessionBusyError()
  chat.reserved = true
  try {
    // The chat's model choice goes in before the prompt (a change made while idle has finished).
    if (chat.configChange) await chat.configChange
    throwIfAborted(opts.signal)
    const choice = pendingModelChoices.get(sessionId)
    if (choice) {
      pendingModelChoices.delete(sessionId)
      try {
        await applyModelChoice(chat, choice)
      } catch (error) {
        console.warn("[acp] sessionId=%s: could not apply the chat's model choice: %s", chat.sessionId, errorText(error))
      }
      throwIfAborted(opts.signal)
    }
  } finally {
    chat.reserved = false
  }
  const carried = chat.sessionId ? carryOver.get(chat.sessionId) : undefined
  if (carried) carryOver.delete(chat.sessionId!)
  const prompt = carried?.length ? [...carried, text].join("\n\n") : text
  const replayFrom = chat.beginPrompt(opts.displayText ?? text, opts.notice)
  const period = chat.period!
  return {
    sessionId: chat.sessionId!,
    replayFrom,
    subscribe: (fn: EventListener) => chat.subscribe(fn),
    send: () => chat.startPrompt(prompt),
    onEnd: () => markSeen(period),
  }
}

/**
 * Send a message into the chat's running turn (`_session/steer`), or, while work holds its
 * period without a turn, start a turn with it. Resolves once it is accepted; the listeners then
 * get its steer event `accepted`, later `delivered` or `discarded`. Throws SteerRejectedError
 * when no period runs (or it was stopped), kiro-cli does not queue it (or does not implement
 * steering: then no later steer is sent to that kiro-cli), or the turn ended meanwhile (the
 * message is then taken back out of kiro-cli's queue).
 */
export async function steerSession(sessionId: string, id: string, text: string): Promise<void> {
  const chat = aliases.get(sessionId)
  if (!chat) throw new SteerRejectedError("session_idle")
  await chat.steer(id, text)
}

/**
 * Stop a chat: a start in progress for the id is aborted (no prompt is sent), and the chat's
 * period's turn and work are cancelled, and nothing starts model work in it any more.
 */
export function cancelSession(sessionId: string): void {
  abortStarts(sessionId)
  aliases.get(sessionId)?.stop()
}

/** Stop every start and every busy chat (stop button with no specific session). */
export function cancelAll(): void {
  abortStarts()
  for (const chat of chats()) if (chat.period) chat.stop()
}

/** Whether a chat is busy (a turn runs, work holds its period, or a prompt is being prepared). */
export function isSessionRunning(sessionId: string): boolean {
  return aliases.get(sessionId)?.busy() ?? false
}

/** The chat's current (else last) period's buffered events, after `afterId` when given (a reconnect's Last-Event-ID). */
export function getBufferedEvents(sessionId: string, afterId?: number): BufferedEvent[] {
  const chat = aliases.get(sessionId)
  const period = chat?.period ?? chat?.lastPeriod
  if (!period) return []
  if (afterId == null) return [...period.buffer]
  return period.buffer.filter((e) => e.id > afterId)
}

/**
 * What `/api/agent/stream` writes for an id (a client id or a kiro session id): a busy chat's
 * period from after `afterId`, then live; a finished period no stream delivered (of a chat, or
 * kept after its chat was released), replayed to its end; else null (nothing runs). `onEnd` marks
 * the period delivered once the stream wrote its end.
 */
export function openStream(id: string, afterId?: number): { replay: BufferedEvent[]; subscribe?: (fn: EventListener) => () => void; onEnd: () => void } | null {
  const chat = aliases.get(id)
  const after = (period: Period) => (afterId == null ? [...period.buffer] : period.buffer.filter((e) => e.id > afterId))
  if (chat?.period) {
    const period = chat.period
    return { replay: after(period), subscribe: (fn) => chat.subscribe(fn), onEnd: () => markSeen(period) }
  }
  const period = chat?.lastPeriod && !chat.lastPeriod.seen ? chat.lastPeriod : unseenById.get(id) ?? null
  if (!period) return null
  return { replay: after(period), onEnd: () => markSeen(period) }
}

/** Subscribe to a chat's events. */
export function subscribeToSession(sessionId: string): { sessionId: string | null; subscribe: (fn: EventListener) => () => void } | null {
  const chat = aliases.get(sessionId)
  if (!chat) return null
  return { sessionId: chat.sessionId, subscribe: (fn: EventListener) => chat.subscribe(fn) }
}

// ── Models ──

/** Keep the engine's model list when a session reported a new one (in memory and acp-models.json). */
function rememberModels(chat: Chat): void {
  const available = chat.hs.engine.models()?.available
  if (!available?.length) return
  const known = knownModels.get(chat.engine) ?? readModelCache(chat.engine)
  knownModels.set(chat.engine, available)
  if (JSON.stringify(known) !== JSON.stringify(available)) writeModelCache(chat.engine, available)
}

/** Change the session's model and effort, after any change still in flight; rejects with kiro-cli's error. */
function applyModelChoice(chat: Chat, choice: ModelChoice): Promise<void> {
  const previous = chat.configChange ?? Promise.resolve()
  const run = previous.then(() => chat.hs.engine.setModel(choice))
  const settled = run.then(() => {
    rememberModels(chat)
    console.log("[acp] sessionId=%s: model %s effort %s", chat.sessionId, choice.model ?? "(unchanged)", choice.effort ?? "(default)")
  }, () => {})
  chat.configChange = settled
  void settled.then(() => { if (chat.configChange === settled) chat.configChange = null })
  return run
}

/** A chat's models as the picker shows them. */
export interface LocalSessionModels {
  engine: EngineId
  available: ModelOption[]
  /** What the chat's session runs (null without a live session that reported it). */
  current: { model: string; effort: string | null; effortLevels: string[] } | null
  /** A choice that applies from the chat's next message. */
  pending: ModelChoice | null
}

/**
 * The models of a chat (`clientId`): its session's list and current model and effort, else the
 * configured engine's last known list (never a new kiro-cli). `pending` is the chat's choice
 * still to apply.
 */
export function getSessionModels(clientId?: string): LocalSessionModels {
  const pending = (clientId && pendingModelChoices.get(clientId)) || null
  const chat = clientId ? aliases.get(clientId) : undefined
  const live = chat && !chat.hs.host.exited ? chat.hs.engine.models() : null
  if (chat && live) {
    return {
      engine: chat.engine,
      available: live.available,
      current: { model: live.current, effort: live.effort?.current ?? null, effortLevels: live.effort?.levels ?? [] },
      pending,
    }
  }
  const engine = readEngineConfig().engine
  return { engine, available: knownModels.get(engine) ?? readModelCache(engine), current: null, pending }
}

/**
 * A chat chose a model and/or effort. Checked against the models it is offered (kiro-cli would
 * take any value): a known model; an effort only for a model with effort levels, one of them.
 * Applied at once when the chat is live and no turn runs or is being prepared (ModelChoiceError
 * `model_not_changed` when kiro-cli refuses, and nothing is kept); otherwise kept for the chat's
 * next message, where a new model drops an effort chosen for the previous one. Answers the
 * chat's models after it.
 */
export async function chooseSessionModel(clientId: string, choice: ModelChoice): Promise<LocalSessionModels> {
  const view = getSessionModels(clientId)
  if (!view.available.length) throw new ModelChoiceError("models_unknown")
  if (choice.model && !view.available.some((model) => model.modelId === choice.model)) throw new ModelChoiceError("unknown_model")
  const pending = view.pending
  if (choice.effort) {
    const target = choice.model ?? pending?.model ?? view.current?.model
    const levels = target && target === view.current?.model
      ? view.current.effortLevels
      : view.available.find((model) => model.modelId === target)?.effortLevels ?? []
    if (!levels.length) throw new ModelChoiceError("effort_not_supported")
    if (!levels.includes(choice.effort)) throw new ModelChoiceError("unknown_effort")
  }
  const merged: ModelChoice = choice.model && choice.model !== pending?.model
    ? { model: choice.model, ...(choice.effort ? { effort: choice.effort } : {}) }
    : { ...pending, ...choice }

  const chat = aliases.get(clientId)
  if (chat && !chat.hs.host.exited && !chat.turn && !chat.reserved && chat.hs.engine.models()) {
    try {
      await applyModelChoice(chat, merged)
    } catch (error) {
      throw new ModelChoiceError("model_not_changed", errorText(error))
    }
    pendingModelChoices.delete(clientId)
  } else {
    keepNewest(pendingModelChoices, clientId, merged, MAX_PENDING_MODEL_CHOICES)
  }
  return getSessionModels(clientId)
}
