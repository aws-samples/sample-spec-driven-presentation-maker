// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP transport: one kiro-cli child process and the JSON-RPC connection over its stdio.
 * Engine-independent: it knows JSON-RPC and the ACP request kiro-cli sends to this client, not
 * what kiro-cli's notifications mean (that is the engine adapters' job, `engines/<id>/`).
 *
 * - A message with a method is a request from kiro-cli (it also has an id) or a notification
 *   (no id); a message with an id and no method answers one of our requests. kiro-cli numbers its
 *   own requests, so their ids may equal ours: they are never taken for answers.
 * - kiro-cli's permission requests are answered with the offered option of kind allow_once (else
 *   allow_always, else reject_once). The optionId comes from the request, never a fixed string,
 *   since V2 and V3 name their options differently; each answer is logged. Any other request is
 *   answered with Method not found (-32601) instead of leaving kiro-cli waiting.
 * - An error answer rejects with AcpRequestError, which keeps the JSON-RPC code and data.
 * - Requests time out (AgentTimeoutError) and follow the caller's abort signal. When the process
 *   exits, every request still waiting is rejected.
 * - The last stderr lines are kept for the log of a kiro-cli that exits while starting.
 * - `detached` (macOS and Linux) starts kiro-cli as the leader of a process group of its own, so its
 *   tree can be ended without the Local server's group (process-tree.ts).
 * - `SDPM_ACP_TRACE` (a file path; unset, nothing is written) gets every line written to and read
 *   from kiro-cli, one JSON line `{t, pid, dir: "out" | "in", msg}`, for the manual E2E.
 */
import { spawn } from "child_process"
import fs from "fs"

import { AgentTimeoutError } from "../turnErrors"
import type { AcpError, AcpNotification, PermissionOption, RequestPermissionRequest, RequestPermissionResponse } from "./schema"

/** JSON-RPC "Method not found", the answer to agent requests this client does not implement. */
export const METHOD_NOT_FOUND = -32601
/** stderr lines kept for `stderrTail`. */
const STDERR_TAIL_LINES = 20

/** An error answer to one of our requests. `message` adds kiro-cli's `data`, where it puts the actual cause. */
export class AcpRequestError extends Error {
  readonly code: number | null
  readonly data: unknown
  constructor(error: Partial<AcpError>) {
    const detail = error.data === undefined ? "" : `: ${typeof error.data === "string" ? error.data : JSON.stringify(error.data)}`
    super(`${error.message || "ACP request failed"}${detail}`)
    this.name = "AcpRequestError"
    this.code = typeof error.code === "number" ? error.code : null
    this.data = error.data
  }
}

/** How a request was answered; handed to `onAnswer` before the request's promise settles. */
export type AcpAnswer = { ok: true; result: unknown } | { ok: false; error: AcpRequestError }

export interface RequestOptions {
  timeoutMs?: number
  signal?: AbortSignal
  /**
   * Called synchronously when the answer's line is read, before the promise settles, so the caller
   * acts on it in line order (the prompt's answer ends the turn before later lines are handled).
   */
  onAnswer?: (answer: AcpAnswer) => void
}

export interface AcpConnection {
  /** The child's pid, undefined when the spawn failed. */
  readonly pid: number | undefined
  /** The child has exited (or failed to spawn); requests to it fail at once. */
  readonly exited: boolean
  /** The child's exit code (null while it runs, or when it was killed or never started). */
  readonly exitCode: number | null
  /** The last lines kiro-cli wrote to stderr. */
  stderrTail(): string[]
  /** Send a request; `id` is its JSON-RPC id. */
  startRequest(method: string, params?: Record<string, unknown>, opts?: RequestOptions): { id: number; response: Promise<unknown> }
  request(method: string, params?: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>
  notify(method: string, params?: Record<string, unknown>): void
  /** Every notification from kiro-cli, in line order. Returns the unsubscribe function. */
  onNotification(fn: (msg: AcpNotification) => void): () => void
  /** Called once when the child exits, after the waiting requests were rejected. */
  onExit(fn: (code: number | null) => void): () => void
  kill(): void
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (reason?: unknown) => void
  onAnswer?: (answer: AcpAnswer) => void
}

let traceWarned = false

/** Append one line to `SDPM_ACP_TRACE` (see the header); a failing write turns the trace off with one warning. */
function trace(pid: number | undefined, dir: "out" | "in", msg: unknown): void {
  const file = process.env.SDPM_ACP_TRACE
  if (!file || traceWarned) return
  try {
    fs.appendFileSync(file, JSON.stringify({ t: Date.now(), pid, dir, msg }) + "\n")
  } catch (error) {
    traceWarned = true
    console.warn("[acp] SDPM_ACP_TRACE: %s; tracing off", error instanceof Error ? error.message : String(error))
  }
}

/** Start `command args` (no shell) and speak JSON-RPC over its stdin and stdout. */
export function spawnAcp(command: string, args: string[], opts: { cwd: string; env: NodeJS.ProcessEnv; detached?: boolean }): AcpConnection {
  const detached = opts.detached === true && process.platform !== "win32"
  const child = spawn(command, args, { cwd: opts.cwd, stdio: ["pipe", "pipe", "pipe"], env: opts.env, ...(detached ? { detached: true } : {}) })
  const pending = new Map<number, Pending>()
  const notificationListeners = new Set<(msg: AcpNotification) => void>()
  const exitListeners = new Set<(code: number | null) => void>()
  let requestId = 0
  let lineBuffer = ""
  let exited = false
  let exitCode: number | null = null
  const stderrLines: string[] = []

  function write(msg: Record<string, unknown>): void {
    if (exited) return
    const line = { jsonrpc: "2.0", ...msg }
    trace(child.pid, "out", line)
    child.stdin!.write(JSON.stringify(line) + "\n")
  }

  function answerPermission(id: unknown, params: Partial<RequestPermissionRequest> | undefined): void {
    const options = (Array.isArray(params?.options) ? params.options : []) as Partial<PermissionOption>[]
    const pick = options.find((o) => o.kind === "allow_once")
      ?? options.find((o) => o.kind === "allow_always")
      ?? options.find((o) => o.kind === "reject_once")
    const outcome: RequestPermissionResponse["outcome"] = pick?.optionId ? { outcome: "selected", optionId: pick.optionId } : { outcome: "cancelled" }
    console.log("[acp] pid %s permission %s \"%s\" → %s", child.pid, params?.toolCall?.kind ?? "-", params?.toolCall?.title ?? "", pick?.optionId ? pick.kind : "cancelled")
    write({ id, result: { outcome } })
  }

  function answerAgentRequest(msg: Record<string, unknown>): void {
    const method = msg.method as string
    if (method === "session/request_permission") {
      answerPermission(msg.id, msg.params as Partial<RequestPermissionRequest> | undefined)
      return
    }
    write({ id: msg.id, error: { code: METHOD_NOT_FOUND, message: `Method not found: ${method}` } })
  }

  function handleLine(line: string): void {
    if (!line.trim()) return
    let msg: Record<string, unknown>
    try { msg = JSON.parse(line) } catch { return }
    if (!msg || typeof msg !== "object") return
    trace(child.pid, "in", msg)

    if (msg.method !== undefined && msg.id != null) {
      answerAgentRequest(msg)
      return
    }
    if (msg.id != null) {
      const waiting = pending.get(msg.id as number)
      if (!waiting) return
      pending.delete(msg.id as number)
      const answer: AcpAnswer = msg.error
        ? { ok: false, error: new AcpRequestError(msg.error as Partial<AcpError>) }
        : { ok: true, result: msg.result }
      waiting.onAnswer?.(answer)
      if (answer.ok) waiting.resolve(answer.result)
      else waiting.reject(answer.error)
      return
    }
    if (typeof msg.method === "string") {
      const notification: AcpNotification = { method: msg.method, params: msg.params }
      for (const fn of notificationListeners) fn(notification)
    }
  }

  child.stdout!.setEncoding("utf-8")
  child.stdout!.on("data", (data: string) => {
    lineBuffer += data
    const lines = lineBuffer.split("\n")
    lineBuffer = lines.pop() || ""
    for (const l of lines) handleLine(l)
  })
  child.stderr!.setEncoding("utf-8")
  child.stderr!.on("data", (d: string) => {
    console.warn("[acp] stderr: %s", d.trim())
    stderrLines.push(...d.split("\n").filter((line) => line.trim()))
    if (stderrLines.length > STDERR_TAIL_LINES) stderrLines.splice(0, stderrLines.length - STDERR_TAIL_LINES)
  })
  // A write racing the exit (a Stop just as kiro-cli dies) fails with EPIPE; the exit handles it.
  child.stdin!.on("error", (error) => console.warn("[acp] stdin: %s", error.message))

  const onClose = (code: number | null) => {
    if (exited) return
    exited = true
    exitCode = code
    for (const waiting of [...pending.values()]) waiting.reject(new Error(`ACP process exited with code ${code}`))
    pending.clear()
    for (const fn of [...exitListeners]) fn(code)
  }
  child.on("close", onClose)
  // kiro-cli's own children (V3's agent server) inherit its stderr and can keep it open for up
  // to a minute after kiro-cli died, which holds back "close" (every stdio stream closed). The
  // exit and the end of stdout (every JSON-RPC line read) are enough to call it exited.
  let stdoutClosed = false
  let exit: { code: number | null } | null = null
  child.stdout!.on("close", () => {
    stdoutClosed = true
    if (exit) onClose(exit.code)
  })
  child.on("exit", (code: number | null) => {
    exit = { code }
    if (stdoutClosed) onClose(code)
  })
  child.on("error", (error) => {
    console.warn("[acp] process error: %s", error.message)
    if (child.pid === undefined) onClose(null) // spawn failed (kiro-cli not found); no close follows
  })

  function startRequest(method: string, params: Record<string, unknown> = {}, opts: RequestOptions = {}): { id: number; response: Promise<unknown> } {
    const id = ++requestId
    const response = new Promise<unknown>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined
      const settle = () => {
        if (timer) clearTimeout(timer)
        opts.signal?.removeEventListener("abort", onAbort)
        pending.delete(id)
      }
      const onAbort = () => { settle(); reject(new DOMException("Request cancelled", "AbortError")) }
      pending.set(id, {
        resolve: (value) => { settle(); resolve(value) },
        reject: (reason) => { settle(); reject(reason) },
        onAnswer: opts.onAnswer,
      })
      if (exited) { settle(); reject(new Error("ACP process has exited")); return }
      if (opts.timeoutMs) timer = setTimeout(() => { settle(); reject(new AgentTimeoutError(method, opts.timeoutMs!)) }, opts.timeoutMs)
      if (opts.signal?.aborted) onAbort()
      else opts.signal?.addEventListener("abort", onAbort, { once: true })
    })
    write({ id, method, params })
    return { id, response }
  }

  return {
    get pid() { return child.pid },
    get exited() { return exited },
    get exitCode() { return exitCode },
    stderrTail: () => [...stderrLines],
    startRequest,
    request: (method, params, opts) => startRequest(method, params, opts).response,
    notify: (method, params = {}) => write({ method, params }),
    onNotification(fn) {
      notificationListeners.add(fn)
      return () => { notificationListeners.delete(fn) }
    },
    onExit(fn) {
      exitListeners.add(fn)
      return () => { exitListeners.delete(fn) }
    },
    kill: () => { child.kill() },
  }
}
