// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The MCP servers' state of a kiro-cli process, per session, and the wait for the sdpm server.
 *
 * A session is ready for a chat once its sdpm server is connected: a prompt sent before runs
 * without the server's tools (a new or forked session then improvises from local files, #404).
 * kiro-cli reports the state on its own, which the engine adapter turns into `mcp_status` (one
 * server) and `mcp_snapshot` (a full snapshot follows, so clear the session) events. The process
 * manager records every one of them from the moment kiro-cli starts: V2 sends them before its
 * answers to session/new, session/load and session/set_mode, so a wait that began after the
 * answer would miss them. A wait therefore reads the record first, then the updates that follow.
 */
import type { LocalEvent, McpStatusEvent } from "./conversation/events"
import { AgentStartError } from "./turnErrors"

export const SDPM_MCP_SERVER = "sdpm"

export type McpServerState = Pick<McpStatusEvent, "state" | "error">

/** The sdpm MCP server reported that it failed to start. */
export class McpFailedError extends AgentStartError {
  constructor(sessionId: string, server: string, error?: string) {
    super("mcp_failed", `MCP server ${server} failed in session ${sessionId}${error ? `: ${error}` : ""}`)
    this.name = "McpFailedError"
  }
}

/** sessionId → server → its latest state. */
export class McpRecord {
  private readonly sessions = new Map<string, Map<string, McpServerState>>()
  private readonly waiters = new Set<() => void>()

  /** Record an `mcp_status` / `mcp_snapshot` event and wake the waits. */
  apply(event: Extract<LocalEvent, { type: "mcp_status" | "mcp_snapshot" }>): void {
    if (event.type === "mcp_snapshot") {
      this.sessions.set(event.sessionId, new Map())
    } else {
      let servers = this.sessions.get(event.sessionId)
      if (!servers) this.sessions.set(event.sessionId, (servers = new Map()))
      servers.set(event.server, { state: event.state, ...(event.error ? { error: event.error } : {}) })
    }
    for (const wake of [...this.waiters]) wake()
  }

  /** Forget a session's state (before set_mode, so the previous mode's `connected` does not count). */
  clear(sessionId: string): void {
    this.sessions.delete(sessionId)
  }

  get(sessionId: string, server: string): McpServerState | undefined {
    return this.sessions.get(sessionId)?.get(server)
  }

  /** Called after every recorded event; returns the function that stops it. */
  subscribe(wake: () => void): () => void {
    this.waiters.add(wake)
    return () => { this.waiters.delete(wake) }
  }
}

/**
 * Wait for a session's MCP server: true once it is connected, false after `timeoutMs` (the
 * caller warns and goes on), McpFailedError when it failed, AbortError when `signal` aborts.
 */
export function waitForMcp(record: McpRecord, sessionId: string, server: string = SDPM_MCP_SERVER, timeoutMs = 120_000, signal?: AbortSignal): Promise<boolean> {
  return new Promise<boolean>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let unsubscribe = () => {}
    const finish = (fn: () => void) => {
      if (timer) clearTimeout(timer)
      signal?.removeEventListener("abort", onAbort)
      unsubscribe()
      fn()
    }
    const onAbort = () => finish(() => reject(new DOMException("Request cancelled", "AbortError")))
    const check = (): boolean => {
      const state = record.get(sessionId, server)
      if (state?.state === "connected") { finish(() => resolve(true)); return true }
      if (state?.state === "failed") { finish(() => reject(new McpFailedError(sessionId, server, state.error))); return true }
      return false
    }
    if (check()) return
    if (signal?.aborted) return onAbort()
    unsubscribe = record.subscribe(() => { check() })
    signal?.addEventListener("abort", onAbort, { once: true })
    timer = setTimeout(() => finish(() => resolve(false)), timeoutMs)
  })
}
