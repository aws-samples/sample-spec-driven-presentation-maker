// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent — API Route that bridges kiro-cli acp via child_process.
 * Local mode only (`NEXT_PUBLIC_MODE=local`).
 */

// Static export compatibility: force-static when not in local mode


import { spawn, type ChildProcess } from "child_process"
import path from "path"
import os from "os"

const DECK_ROOT = path.join(os.homedir(), "Documents", "SDPM-Presentations")

let child: ChildProcess | null = null
let requestId = 0
let sessionId: string | null = null

type PendingResolve = (value: unknown) => void
const pending = new Map<number, PendingResolve>()

// Listeners for streaming notifications
let notifyCallback: ((msg: Record<string, unknown>) => void) | null = null

function rpcRequest(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!child) throw new Error("ACP agent not started")
  const id = ++requestId
  const msg = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n"
  child.stdin!.write(msg)
  return new Promise((resolve) => { pending.set(id, resolve) })
}

function handleLine(line: string) {
  if (!line.trim()) return
  let msg: Record<string, unknown>
  try { msg = JSON.parse(line) } catch { return }

  // JSON-RPC response
  if (msg.id != null && pending.has(msg.id as number)) {
    const resolve = pending.get(msg.id as number)!
    pending.delete(msg.id as number)
    resolve(msg.result)
    // Also forward to notify for end_turn detection
    if (notifyCallback) notifyCallback(msg)
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

  // Forward all notifications to the active listener
  if (notifyCallback) notifyCallback(msg)
}

let lineBuffer = ""

async function ensureAgent(): Promise<void> {
  if (child) return

  const projectRoot = process.cwd()
  child = spawn("kiro-cli", ["acp", "--agent", "sdpm-spec"], {
    cwd: projectRoot,
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
  })

  // Initialize
  await rpcRequest("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
    clientInfo: { name: "sdpm-local", version: "0.1.0" },
  })

  // Create session
  const result = await rpcRequest("session/new", { cwd: DECK_ROOT, mcpServers: [] }) as Record<string, unknown>
  sessionId = result.sessionId as string
}

// Cleanup on process exit
for (const sig of ["exit", "SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => { child?.kill(); child = null })
}

export async function POST(req: Request) {
  const { query, sessionId: clientSessionId } = await req.json()

  await ensureAgent()

  // If client requests a new chat session, create a new ACP session
  if (clientSessionId && clientSessionId !== sessionId) {
    try {
      const result = await rpcRequest("session/new", { cwd: DECK_ROOT, mcpServers: [] }) as Record<string, unknown>
      sessionId = result.sessionId as string
    } catch {
      // Restart process on failure
      child?.kill()
      child = null
      sessionId = null
      await ensureAgent()
    }
  }

  // Stream SSE back to browser
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      let completion = ""
      let subagentToolCallId: string | null = null
      let totalGroups = 0
      const subagentGroups = new Map<string, { group: number; slugs: string }>()
      const subagentQueryQueue: string[] = []

      function extractSlugs(q: string): string {
        const m = q.match(/slides?:\s*([a-z0-9,\-\s]+?)(?:\.|$|\n)/i)
        return m ? m[1].trim() : ""
      }

      function send(event: Record<string, unknown>) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }

      notifyCallback = (msg) => {
        // End turn detection from RPC response
        if (msg.id != null && msg.result) {
          const r = msg.result as Record<string, unknown>
          if (r.stopReason === "end_turn" || r.stopReason === "cancelled") {
            controller.close()
            notifyCallback = null
            return
          }
        }

        if (msg.method !== "session/update" && msg.method !== "_kiro.dev/session/update") return
        const params = msg.params as Record<string, unknown>
        const msgSessionId = params.sessionId as string
        const update = params.update as Record<string, unknown>
        if (!update) return
        const type = update.sessionUpdate as string

        // Subagent session — forward as compose_slides stream events
        if (msgSessionId !== sessionId && subagentToolCallId) {
          let groupInfo = subagentGroups.get(msgSessionId)
          if (!groupInfo) {
            const idx = subagentGroups.size
            const slugs = subagentQueryQueue[idx] || `group ${idx + 1}`
            groupInfo = { group: idx + 1, slugs }
            subagentGroups.set(msgSessionId, groupInfo)
            send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: groupInfo.group, total_groups: totalGroups, slugs: groupInfo.slugs, status: "starting" } } })
          }
          if (type === "tool_call") {
            const title = (update.title || "") as string
            const toolName = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
            send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: groupInfo.group, slugs: groupInfo.slugs, tool: toolName } } })
          } else if (type === "tool_call_update") {
            const status = update.status as string
            if (status === "completed" || status === "error" || status === "failed") {
              send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: groupInfo.group, slugs: groupInfo.slugs, toolResult: update.toolCallId, toolStatus: status === "completed" ? "success" : "error" } } })
            }
          } else if (type === "turn_end" || type === "end_turn") {
            send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: groupInfo.group, slugs: groupInfo.slugs, status: "done" } } })
          }
          return
        }

        if (msgSessionId !== sessionId) return

        if (type === "agent_message_chunk") {
          const content = update.content as Record<string, unknown>
          if (content?.text) {
            completion += content.text as string
            send({ event: { contentBlockDelta: { delta: { text: content.text } } } })
          }
        }

        if (type === "tool_call" || type === "tool_call_chunk") {
          const toolCallId = update.toolCallId as string || ""
          const title = (update.title || update.name || "") as string
          let name = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
          const input = (update.rawInput || update.input || {}) as Record<string, unknown>
          const isSubagentCall = title === "Spawning agent crew" || name === "subagent"
          if (isSubagentCall) {
            subagentToolCallId = toolCallId
            subagentGroups.clear()
            const content = (input.content as Record<string, unknown> | undefined) || input
            const queries = (content.queries as string[]) || []
            totalGroups = queries.length
            subagentQueryQueue.length = 0
            queries.forEach((q: string) => subagentQueryQueue.push(extractSlugs(q)))
            name = "compose_slides"
          }
          send({ toolStart: { toolUseId: toolCallId, name } })
        }

        if (type === "tool_call_update") {
          const toolCallId = update.toolCallId as string || ""
          const title = (update.title || "") as string
          let toolName = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
          if (toolCallId === subagentToolCallId) toolName = "compose_slides"
          const status = update.status as string
          if (status === "completed") {
            let result: Record<string, unknown> = {}
            try {
              const rawOutput = update.rawOutput as Record<string, unknown>
              const items = rawOutput?.items as Array<Record<string, unknown>>
              if (items?.[0]) {
                const json = items[0].Json as Record<string, unknown>
                const content = json?.content as Array<Record<string, unknown>>
                if (content?.[0]?.text) result = JSON.parse(content[0].text as string)
              }
            } catch {}
            if (result.output_dir && !result.deckId) {
              result.deckId = (result.output_dir as string).split("/").pop() || ""
            }
            send({ toolResult: { toolUseId: toolCallId, name: toolName, status: "success", content: JSON.stringify(result) } })
          }
        }

        if (type === "turn_end" || type === "end_turn") {
          controller.close()
          notifyCallback = null
        }
      }

      // Send prompt
      rpcRequest("session/prompt", {
        sessionId,
        prompt: [{ type: "text", text: query }],
      }).then((res) => {
        const r = res as Record<string, unknown> | undefined
        if (r?.stopReason === "end_turn" || r?.stopReason === "cancelled") {
          try { controller.close() } catch {}
          notifyCallback = null
        }
      })
    },
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
