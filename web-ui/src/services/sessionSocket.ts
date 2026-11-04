// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SessionSocket — the WebSocket to one Cloud session (the agent's `/ws` entry).
 *
 * One connection per work period: it opens when the page sends something, and closes
 * when the session goes idle with nothing left unanswered (R5: an idle tab keeps no
 * connection, so the VM is reclaimed as before).
 *
 * - The token goes as the subprotocol `base64UrlBearerAuthorization.<base64url>`, with
 *   the bare `base64UrlBearerAuthorization` the platform answers with.
 * - The client speaks first: nothing is expected from the server before a message is sent.
 * - Frames are a control message (`{"ctl"}`), one item (`{"seq","ev"}`), a batch of items
 *   (`{"batch":[…]}`) or one part of an item too large for a frame (`{"chunk","i","n","data"}`).
 *   Items reach the listener in seq order; one already seen is dropped.
 * - While the session works: an app ping every 30 s (the platform closes a connection after
 *   60 s without a message), and after an unexpected close, reconnects with backoff and
 *   `resume {from_seq: lastSeq}`. A tab coming back (`visibilitychange`) or the network coming
 *   back (`online`) reconnects at once. No reconnect while idle, or after a refusal (4403).
 * - The last known state and seq are kept in localStorage (lib/sessionState.ts) for a reload.
 */

import { createSessionStateWriter, type SessionStateWriter } from "@/lib/sessionState"

export const SUBPROTOCOL = "base64UrlBearerAuthorization"
export const PING_INTERVAL_MS = 30_000
export const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10_000, 10_000]
/** Close code the agent uses when it refuses a connection (owner check). */
export const REFUSED_CLOSE_CODE = 4403
/** The `error` text the agent sends when a prepare failed (ws_entry.Connection._ready). */
export const PREPARE_FAILED = "Prepare failed"
const WS_OPEN = 1

export type SessionEvent = Record<string, unknown>
export interface SessionItem { seq: number; ev: SessionEvent }
export interface SessionCtl { ctl: string; [key: string]: unknown }

export interface SessionClosedInfo {
  code: number
  /** Messages sent that got no answer before the connection closed (ids, "resume", "prepare", "cancel:<id>"). */
  lost: string[]
  /** A reconnect is scheduled. */
  reconnecting: boolean
  /** Reconnects ran out (or the connection was refused) while the session was working. */
  gaveUp: boolean
}

export interface SessionSocketListener {
  onItem: (item: SessionItem) => void
  /** `answered`: the message this control message answers, when it answers one. */
  onCtl: (ctl: SessionCtl, answered?: string) => void
  onReconnecting?: (active: boolean) => void
  onClosed?: (info: SessionClosedInfo) => void
}

export interface SessionSocketOptions {
  url: string
  sessionId: string
  getToken: () => string | undefined
  listener: SessionSocketListener
}

type Outgoing = Record<string, unknown> & { type: string }

/** base64url of an ASCII string (a JWT), without padding. */
export function base64Url(text: string): string {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

export class SessionSocket {
  readonly sessionId: string
  /** "working" from `work busy` (or a message accepted as a turn) until `work idle`. */
  working = false
  lastSeq = 0

  private readonly url: string
  private readonly getToken: () => string | undefined
  private readonly listener: SessionSocketListener
  private readonly stateWriter: SessionStateWriter
  private ws: WebSocket | null = null
  private outbox: string[] = []
  /** Messages waiting for their answer, oldest first. */
  private pending: string[] = []
  private holds = 0
  private chunks = new Map<string, { n: number; parts: string[]; got: number }>()
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private attempts = 0
  private reconnecting = false
  private refused = false
  private windowHooked = false
  /** After a resume of work that ended: the last seq of its replay (0: none pending). */
  private replayUntil = 0

  constructor({ url, sessionId, getToken, listener }: SessionSocketOptions) {
    this.url = url
    this.sessionId = sessionId
    this.getToken = getToken
    this.listener = listener
    this.stateWriter = createSessionStateWriter(sessionId)
  }

  /** A connection is open or opening. */
  get connected(): boolean {
    return this.ws !== null
  }

  get pendingCount(): number {
    return this.pending.length
  }

  /** Send a message, opening the connection when there is none. */
  send(message: Outgoing): void {
    const key = this.answerKey(message)
    if (key) this.pending.push(key)
    this.outbox.push(JSON.stringify(message))
    if (this.reconnectTimer) return // the reconnect sends it after its resume
    if (!this.ws) {
      this.refused = false
      this.open()
    } else {
      this.drain()
    }
  }

  /** Keep the connection open while idle (a prepare waiting for `ready`). */
  hold(): void {
    this.holds += 1
  }

  release(): void {
    this.holds = Math.max(0, this.holds - 1)
    this.closeIfSettled()
  }

  /** Stop waiting for the answer to a message (its caller gave up). */
  forget(key: string): void {
    this.answered(key)
    this.closeIfSettled()
  }

  /** Close on purpose (no reconnect). Unanswered messages are dropped. */
  close(): void {
    this.cancelReconnect()
    this.outbox = []
    this.pending = []
    this.holds = 0
    this.replayUntil = 0
    this.chunks.clear()
    this.stopPing()
    this.unhookWindow()
    const ws = this.ws
    this.ws = null
    if (ws) {
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null
      try { ws.close(1000) } catch { /* already closing */ }
    }
  }

  /** Forget the session's work (the page stopped following it). */
  markIdle(): void {
    this.setWorking(false)
    this.stateWriter.flush()
  }

  // -- connection ---------------------------------------------------------------

  private answerKey(message: Outgoing): string | null {
    switch (message.type) {
      case "prompt":
      case "steer":
        return String(message.id ?? "")
      case "resume":
        return "resume"
      case "prepare":
        return "prepare"
      case "cancel":
        return `cancel:${String(message.id ?? "")}`
      default:
        return null
    }
  }

  private open(): void {
    const token = this.getToken() ?? ""
    let ws: WebSocket
    try {
      ws = new WebSocket(this.url, [`${SUBPROTOCOL}.${base64Url(token)}`, SUBPROTOCOL])
    } catch (err) {
      console.error("WebSocket open failed:", err)
      this.handleClose(1006)
      return
    }
    this.ws = ws
    if (this.working) this.hookWindow()
    ws.onopen = () => {
      if (this.ws !== ws) return
      this.drain()
    }
    ws.onmessage = (event: MessageEvent) => {
      if (this.ws !== ws) return
      this.receive(typeof event.data === "string" ? event.data : "")
    }
    ws.onclose = (event: CloseEvent) => {
      if (this.ws !== ws) return
      this.ws = null
      this.handleClose(event.code)
    }
  }

  private drain(): void {
    const ws = this.ws
    if (!ws || ws.readyState !== WS_OPEN) return
    const out = this.outbox
    this.outbox = []
    for (const text of out) ws.send(text)
  }

  private handleClose(code: number): void {
    this.stopPing()
    this.chunks.clear()
    this.replayUntil = 0
    const lost = this.pending
    this.pending = []
    this.outbox = []
    if (code === REFUSED_CLOSE_CODE) this.refused = true
    const canRetry = this.working && !this.refused && this.attempts < RECONNECT_DELAYS_MS.length
    if (canRetry) {
      const delay = RECONNECT_DELAYS_MS[this.attempts]
      this.attempts += 1
      this.setReconnecting(true)
      this.reconnectTimer = setTimeout(() => this.reconnect(), delay)
    } else {
      this.setReconnecting(false)
      // Idle, refused or out of attempts: nothing reconnects until the page sends again.
      this.unhookWindow()
    }
    this.listener.onClosed?.({ code, lost, reconnecting: canRetry, gaveUp: this.working && !canRetry })
  }

  private reconnect(): void {
    this.reconnectTimer = null
    if (this.ws || !this.working) return
    const queued = this.outbox
    this.outbox = []
    // A resume the page queued meanwhile (a deck opened again) replaces the reconnect's own.
    const pageResume = queued.some((text) => (JSON.parse(text) as Outgoing).type === "resume")
    if (!pageResume) {
      this.pending = this.pending.filter((key) => key !== "resume")
      this.pending.unshift("resume")
      this.outbox.push(JSON.stringify({ type: "resume", from_seq: this.lastSeq }))
    }
    this.outbox.push(...queued)
    this.open()
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.setReconnecting(false)
  }

  private setReconnecting(active: boolean): void {
    if (this.reconnecting === active) return
    this.reconnecting = active
    this.listener.onReconnecting?.(active)
  }

  /** The tab is visible again or the network is back: reconnect now if the session works. */
  private readonly wake = () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return
    if (!this.working || this.ws || this.refused) return
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.attempts = 0
    this.setReconnecting(true)
    this.reconnect()
  }

  private hookWindow(): void {
    if (this.windowHooked || typeof window === "undefined") return
    this.windowHooked = true
    document.addEventListener("visibilitychange", this.wake)
    window.addEventListener("online", this.wake)
  }

  private unhookWindow(): void {
    if (!this.windowHooked) return
    this.windowHooked = false
    document.removeEventListener("visibilitychange", this.wake)
    window.removeEventListener("online", this.wake)
  }

  // -- state ----------------------------------------------------------------------

  private setWorking(working: boolean): void {
    if (this.working !== working) {
      this.working = working
      if (working) {
        this.hookWindow()
      } else {
        this.stopPing()
        this.attempts = 0
      }
    }
    // Also after a reconnect, whose close stopped the ping while the session kept working.
    if (working) this.startPing()
    this.stateWriter.update(working ? "working" : "idle", this.lastSeq)
  }

  private startPing(): void {
    if (this.pingTimer) return
    this.pingTimer = setInterval(() => {
      const ws = this.ws
      if (ws && ws.readyState === WS_OPEN) ws.send(JSON.stringify({ type: "ping" }))
    }, PING_INTERVAL_MS)
  }

  private stopPing(): void {
    if (this.pingTimer) clearInterval(this.pingTimer)
    this.pingTimer = null
  }

  private closeIfSettled(): void {
    if (!this.working && this.pending.length === 0 && this.holds === 0 && this.lastSeq >= this.replayUntil && this.ws) {
      this.close()
      this.stateWriter.flush()
    }
  }

  private answered(key: string | undefined): string | undefined {
    if (key === undefined) return undefined
    const i = this.pending.indexOf(key)
    if (i < 0) return undefined
    this.pending.splice(i, 1)
    return key
  }

  // -- frames ---------------------------------------------------------------------

  private receive(text: string): void {
    let frame: Record<string, unknown>
    try {
      frame = JSON.parse(text)
    } catch {
      console.debug("Unreadable session frame")
      return
    }
    if (!frame || typeof frame !== "object") return
    if (typeof frame.ctl === "string") {
      this.control(frame as SessionCtl)
    } else if (Array.isArray(frame.batch)) {
      for (const item of frame.batch) this.item(item as SessionItem)
    } else if (typeof frame.chunk === "string") {
      this.chunk(frame.chunk, Number(frame.i), Number(frame.n), String(frame.data ?? ""))
    } else if (typeof frame.seq === "number") {
      this.item(frame as unknown as SessionItem)
    }
  }

  private chunk(id: string, i: number, n: number, data: string): void {
    if (!Number.isInteger(i) || !Number.isInteger(n) || n <= 0 || i < 0 || i >= n) return
    let entry = this.chunks.get(id)
    if (!entry) {
      entry = { n, parts: new Array<string>(n), got: 0 }
      this.chunks.set(id, entry)
    }
    if (entry.parts[i] === undefined) {
      entry.parts[i] = data
      entry.got += 1
    }
    if (entry.got < entry.n) return
    this.chunks.delete(id)
    try {
      this.item(JSON.parse(entry.parts.join("")) as SessionItem)
    } catch {
      console.debug("Unreadable chunked session item")
    }
  }

  private item(item: SessionItem): void {
    if (!item || typeof item.seq !== "number" || !item.ev || typeof item.ev !== "object") return
    if (item.seq <= this.lastSeq) return
    this.lastSeq = item.seq
    const work = (item.ev as { work?: { state?: string } }).work
    if (work?.state === "busy") this.setWorking(true)
    this.listener.onItem(item)
    if (work?.state === "idle") {
      this.setWorking(false)
      this.closeIfSettled()
    } else {
      this.stateWriter.update(this.working ? "working" : "idle", this.lastSeq)
      if (this.replayUntil && this.lastSeq >= this.replayUntil) this.closeIfSettled()
    }
  }

  private control(ctl: SessionCtl): void {
    let answered: string | undefined
    switch (ctl.ctl) {
      case "pong":
      case "keepalive":
        return
      case "accepted": {
        answered = this.answered(String(ctl.id ?? ""))
        // A process that started over numbers from 1 again.
        if (typeof ctl.head === "number" && ctl.head < this.lastSeq) this.lastSeq = 0
        // As a turn or as a steer, the session is working now.
        this.setWorking(true)
        break
      }
      case "resumeAck": {
        answered = this.answered("resume")
        // The server sends everything from `replay_from` again: a resume from 0 on an open
        // connection (a deck opened again) gets its replay, and a process that started over
        // numbers from 1 again.
        if (typeof ctl.replay_from === "number") {
          this.lastSeq = Math.max(0, ctl.replay_from - 1)
        } else if (typeof ctl.head === "number" && ctl.head < this.lastSeq) {
          this.lastSeq = 0
        }
        this.setReconnecting(false)
        this.attempts = 0
        const working = ctl.working === true
        const head = typeof ctl.head === "number" ? ctl.head : 0
        const replayFrom = typeof ctl.replay_from === "number" ? ctl.replay_from : head + 1
        // Work that ended while away: stay open for its replay (it ends with `work idle`).
        this.replayUntil = !working && replayFrom <= head ? head : 0
        this.setWorking(working)
        break
      }
      case "prepareAck":
        answered = this.answered("prepare")
        break
      case "cancelAck":
        answered = this.answered(`cancel:${String(ctl.id ?? "")}`)
        if (ctl.result === "idle") this.setWorking(false)
        break
      case "error":
        if (ctl.code === "auth") this.refused = true
        // A failed prepare answers late; any other error answers the oldest message.
        if (ctl.error !== PREPARE_FAILED) answered = this.pending.shift()
        break
      default:
        break
    }
    this.listener.onCtl(ctl, answered)
    this.closeIfSettled()
  }
}
