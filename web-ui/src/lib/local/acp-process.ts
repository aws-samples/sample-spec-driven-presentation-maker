// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Process Manager — spawns and manages a single kiro-cli acp child process.
 *
 * Provides JSON-RPC request/response and notification subscription.
 * Singleton: one process shared across all API route invocations.
 */
import { spawn, type ChildProcess } from "child_process"
import path from "path"
import os from "os"

export const DECK_ROOT = path.join(os.homedir(), "Documents", "SDPM-Presentations")

type PendingResolve = (value: unknown) => void
type NotifyListener = (msg: Record<string, unknown>) => void

let child: ChildProcess | null = null
let requestId = 0
let sessionId: string | null = null
const pending = new Map<number, PendingResolve>()
const listeners = new Set<NotifyListener>()
let lineBuffer = ""

function handleLine(line: string) {
  if (!line.trim()) return
  let msg: Record<string, unknown>
  try { msg = JSON.parse(line) } catch { return }

  // JSON-RPC response
  if (msg.id != null && pending.has(msg.id as number)) {
    const resolve = pending.get(msg.id as number)!
    pending.delete(msg.id as number)
    resolve(msg.result)
    // Also notify listeners for end_turn detection
    for (const fn of listeners) fn(msg)
    return
  }

  // Auto-approve permission requests
  if (msg.method === "session/request_permission") {
    const reqId = msg.id as string
    if (reqId && child) {
      child.stdin!.write(JSON.stringify({
        jsonrpc: "2.0", id: reqId, result: { optionId: "allow_always" },
      }) + "\n")
    }
    return
  }

  // Forward notifications to all listeners
  for (const fn of listeners) fn(msg)
}

/** Send a JSON-RPC request and await the response. */
export function rpcRequest(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!child) throw new Error("ACP agent not started")
  const id = ++requestId
  const msg = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n"
  child.stdin!.write(msg)
  return new Promise((resolve) => { pending.set(id, resolve) })
}

/** Subscribe to JSON-RPC notifications. Returns unsubscribe function. */
export function subscribe(fn: NotifyListener): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** Send a fire-and-forget JSON-RPC notification (no id, no response). */
export function rpcNotify(method: string, params: Record<string, unknown> = {}): void {
  if (!child) return
  child.stdin!.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n")
}

/** Get the current ACP session ID. */
export function getSessionId(): string | null { return sessionId }

export interface AcpModel { modelId: string; name: string; description?: string }

let currentModelId = ""
let availableModels: AcpModel[] = []

/** Get available models (populated after ensureAgent). */
export function getModels(): { current: string; available: AcpModel[] } {
  return { current: currentModelId, available: availableModels }
}

/** Set a session config option (e.g. model selection). */
export async function setConfigOption(configId: string, value: string): Promise<void> {
  if (!child || !sessionId) return
  await rpcRequest("session/set_config_option", { sessionId, configId, value })
}

/** Ensure the ACP process is running and a session exists. */
export async function ensureAgent(): Promise<void> {
  if (child) return

  child = spawn("kiro-cli", ["acp", "--agent", "sdpm-spec"], {
    cwd: process.cwd(),
    stdio: ["pipe", "pipe", "pipe"],
  })

  child.stdout!.setEncoding("utf-8")
  child.stdout!.on("data", (data: string) => {
    lineBuffer += data
    const lines = lineBuffer.split("\n")
    lineBuffer = lines.pop() || ""
    for (const l of lines) handleLine(l)
  })

  child.stderr!.setEncoding("utf-8")
  child.stderr!.on("data", (d: string) => console.warn("[acp stderr]", d))

  child.on("close", () => {
    child = null
    sessionId = null
    pending.clear()
    listeners.clear()
  })

  await rpcRequest("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
    clientInfo: { name: "sdpm-local", version: "0.1.0" },
  })

  const result = await rpcRequest("session/new", { cwd: DECK_ROOT, mcpServers: [] }) as Record<string, unknown>
  sessionId = result.sessionId as string

  // Extract model info from session/new response
  type ConfigOption = { id: string; category?: string; currentValue: string; options: { value: string; name: string; description?: string }[] }
  const configOptions = result.configOptions as ConfigOption[] | undefined
  const modelOpt = configOptions?.find(o => o.category === "model" || o.id === "model")
  if (modelOpt) {
    currentModelId = modelOpt.currentValue
    availableModels = modelOpt.options
      .filter(o => !o.description?.startsWith("[Internal]") && !o.description?.startsWith("[Deprecated]"))
      .map(o => ({ modelId: o.value, name: o.name, description: o.description }))
  }

  // Apply stored model preference
  const storedModel = typeof sessionStorage !== "undefined" ? null : null // server-side, no sessionStorage
  // Model preference is managed client-side via /api/agent/models PUT
}
}

/** Create a new ACP session (for new chat). */
export async function newSession(): Promise<void> {
  const result = await rpcRequest("session/new", { cwd: DECK_ROOT, mcpServers: [] }) as Record<string, unknown>
  sessionId = result.sessionId as string
}

// Cleanup on process exit
for (const sig of ["exit", "SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => { child?.kill(); child = null })
}
