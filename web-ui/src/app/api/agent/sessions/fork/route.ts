// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Fork a stored kiro-cli session with the configured agent engine and stream the fork's
 * progress as SSE (`phase`, then `done` or `error`). The client names only the source's id; the
 * source is looked up here (the session catalog), so the origin shown with the chat comes from
 * kiro-cli's store, and a session the engine cannot open is refused (404). A fork kiro-cli could
 * not read fails (502): a chat must not continue "from" a session without its history. A fork
 * that fails or is cancelled once it exists is deleted again; the source is never changed.
 */
import { discardForkedSession, forkSession, pendingOrigins } from "@/lib/local/acp-process"
import { findSession } from "@/lib/local/kiro-sessions"
import type { ForkSessionPhase, ForkSessionPhaseDetail, ForkSessionRequest, SessionOrigin } from "@/lib/local/kiro-sessions.types"
import { rejectCrossSite } from "@/lib/local/requestGuard"

export const dynamic = "force-dynamic"

/** A kiro session id: V2 UUID, V3 `sess_<uuid>`. */
const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/

class SourceNotFoundError extends Error {
  constructor() {
    super("kiro session not found")
    this.name = "SourceNotFoundError"
  }
}

export async function POST(req: Request) {
  const refused = rejectCrossSite(req)
  if (refused) return refused
  let body: Partial<ForkSessionRequest>
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  if (!body.sourceSessionId || !body.clientSessionId) {
    return Response.json({ error: "sourceSessionId and clientSessionId required" }, { status: 400 })
  }
  if (typeof body.sourceSessionId !== "string" || !SESSION_ID_PATTERN.test(body.sourceSessionId)) {
    return Response.json({ error: "invalid kiro session ID" }, { status: 400 })
  }
  const sourceSessionId = body.sourceSessionId
  const agentName = body.agentName || "sdpm-orchestrator"

  const encoder = new TextEncoder()
  const operationController = new AbortController()
  let forkId: string | null = null
  let completed = false
  let cleanupPromise: Promise<void> | null = null

  /** Delete a fork that exists but was not handed to the client (`forkSession` cleans up before that). */
  function cleanupFork(): Promise<void> {
    if (!forkId) return Promise.resolve()
    cleanupPromise ??= discardForkedSession(forkId)
    return cleanupPromise
  }

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false

      function send(event: "phase" | "done" | "error", data: Record<string, unknown>) {
        if (closed) return
        try {
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
        } catch {
          closed = true
        }
      }

      function close() {
        if (closed) return
        closed = true
        try { controller.close() } catch {}
      }

      function onAbort() {
        if (completed) return
        operationController.abort()
        void cleanupFork().finally(close)
      }
      if (req.signal.aborted) onAbort()
      else req.signal.addEventListener("abort", onAbort, { once: true })

      const cancelled = () => new DOMException("Fork cancelled", "AbortError")

      void (async () => {
        try {
          if (operationController.signal.aborted) throw cancelled()
          const source = await findSession(sourceSessionId)
          if (!source) throw new SourceNotFoundError()
          if (operationController.signal.aborted) throw cancelled()

          const fork = await forkSession(source.sessionId, agentName, {
            signal: operationController.signal,
            onPhase: (phase: ForkSessionPhase, detail?: ForkSessionPhaseDetail) => {
              send("phase", { phase, ...detail })
            },
          })
          forkId = fork.sessionId
          if (operationController.signal.aborted) throw cancelled()

          const origin: SessionOrigin = {
            sourceSessionId: source.sessionId,
            title: source.title,
            cwd: source.cwd,
            updatedAt: source.updatedAt,
            forkedAt: new Date().toISOString(),
          }
          pendingOrigins.set(fork.sessionId, origin)
          completed = true
          req.signal.removeEventListener("abort", onAbort)
          send("done", { sessionId: fork.sessionId, origin })
          close()
        } catch (error) {
          req.signal.removeEventListener("abort", onAbort)
          await cleanupFork()
          if (operationController.signal.aborted || (error instanceof Error && error.name === "AbortError")) {
            close()
            return
          }
          const message = error instanceof Error ? error.message : "failed to fork session"
          const code = error instanceof SourceNotFoundError ? 404 : 502
          if (code === 502) console.warn("[fork] %s: %s", sourceSessionId, message)
          send("error", { error: message, code })
          close()
        }
      })()
    },
    cancel() {
      if (!completed) {
        operationController.abort()
        void cleanupFork()
      }
    },
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  })
}
