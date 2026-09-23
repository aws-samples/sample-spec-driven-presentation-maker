// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Fork a kiro-cli session and stream copy/load progress as SSE. */
import { getOrCreateProcess, pendingOrigins, terminateProcess } from "@/lib/local/acp-process"
import { forkSession, removeForkedSession } from "@/lib/local/kiro-sessions"
import type { ForkSessionRequest, ForkSessionPhase, ForkSessionPhaseDetail } from "@/lib/local/kiro-sessions.types"

export const dynamic = "force-dynamic"

export async function POST(req: Request) {
  let body: Partial<ForkSessionRequest>
  try {
    body = await req.json()
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 })
  }
  if (!body.sourceSessionId || !body.clientSessionId) {
    return Response.json({ error: "sourceSessionId and clientSessionId required" }, { status: 400 })
  }

  const encoder = new TextEncoder()
  const operationController = new AbortController()
  let forkId: string | null = null
  let completed = false
  let cleanupPromise: Promise<void> | null = null

  function cleanupFork(): Promise<void> {
    if (!forkId) return Promise.resolve()
    if (!cleanupPromise) {
      terminateProcess(forkId)
      cleanupPromise = removeForkedSession(forkId)
    }
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

      void (async () => {
        try {
          if (operationController.signal.aborted) throw new DOMException("Fork cancelled", "AbortError")
          send("phase", { phase: "copying" satisfies ForkSessionPhase })
          const fork = await forkSession(body.sourceSessionId!)
          forkId = fork.newId
          if (operationController.signal.aborted) throw new DOMException("Fork cancelled", "AbortError")

          await getOrCreateProcess(fork.newId, body.agentName || "sdpm-orchestrator", {
            setMode: true,
            signal: operationController.signal,
            onPhase: (phase: ForkSessionPhase, detail?: ForkSessionPhaseDetail) => {
              send("phase", { phase, ...detail })
            },
          })
          if (operationController.signal.aborted) throw new DOMException("Fork cancelled", "AbortError")

          pendingOrigins.set(fork.newId, fork.origin)
          completed = true
          req.signal.removeEventListener("abort", onAbort)
          send("done", { sessionId: fork.newId, origin: fork.origin })
          close()
        } catch (error) {
          req.signal.removeEventListener("abort", onAbort)
          await cleanupFork()
          if (operationController.signal.aborted || (error instanceof Error && error.name === "AbortError")) {
            close()
            return
          }

          const fsCode = (error as NodeJS.ErrnoException).code
          const message = error instanceof Error ? error.message : "failed to fork session"
          const code = message.includes("invalid kiro session ID") ? 400 : fsCode === "ENOENT" ? 404 : 502
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
