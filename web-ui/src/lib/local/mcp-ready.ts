// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Wait for an MCP server to finish initializing in an ACP session.
 *
 * `session/set_mode` answers before the new agent's MCP servers are up: kiro-cli
 * reports readiness separately as `_kiro.dev/mcp/server_initialized`. A prompt sent
 * in between runs without the server's tools — a forked session then greets the user
 * without `start_presentation` and improvises from local files.
 */

export const MCP_SERVER_INITIALIZED = "_kiro.dev/mcp/server_initialized"
export const SDPM_MCP_SERVER = "sdpm"

type Listener = (msg: Record<string, unknown>) => void

export interface McpReadyWatch {
  /** Resolves true once the server is up, false after `timeoutMs`; rejects on abort. */
  wait: (timeoutMs?: number, signal?: AbortSignal) => Promise<boolean>
  /** Stop listening (safe to call more than once). */
  dispose: () => void
}

/**
 * Start watching before the requests that may start the server (`session/load`,
 * `session/set_mode`): the notification can arrive ahead of their responses.
 * The timeout only runs inside `wait`, so a long session replay does not eat it.
 */
export function watchMcpServerReady(
  listeners: Set<Listener>,
  sessionId: string,
  serverName: string = SDPM_MCP_SERVER,
): McpReadyWatch {
  let seen = false
  let onSeen: (() => void) | null = null

  const listener: Listener = (msg) => {
    if (msg.method !== MCP_SERVER_INITIALIZED) return
    const params = msg.params as { sessionId?: string; serverName?: string } | undefined
    if (params?.sessionId !== sessionId || params?.serverName !== serverName) return
    seen = true
    onSeen?.()
  }
  listeners.add(listener)
  const dispose = () => { listeners.delete(listener) }

  function wait(timeoutMs = 120_000, signal?: AbortSignal): Promise<boolean> {
    return new Promise<boolean>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined
      const finish = (fn: () => void) => {
        if (timer) clearTimeout(timer)
        signal?.removeEventListener("abort", onAbort)
        onSeen = null
        dispose()
        fn()
      }
      const onAbort = () => finish(() => reject(new DOMException("Fork cancelled", "AbortError")))
      if (seen) return finish(() => resolve(true))
      if (signal?.aborted) return onAbort()
      onSeen = () => finish(() => resolve(true))
      signal?.addEventListener("abort", onAbort, { once: true })
      timer = setTimeout(() => finish(() => resolve(false)), timeoutMs)
    })
  }
  return { wait, dispose }
}
