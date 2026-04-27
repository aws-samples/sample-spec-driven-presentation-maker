// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SSE Bridge — translates kiro-cli acp JSON-RPC notifications into
 * SSE events matching the strandsParser format used by the web-ui.
 *
 * Returns a ReadableStream that the API route can return as a Response.
 */

interface BridgeOptions {
  sessionId: string
  subscribe: (fn: (msg: Record<string, unknown>) => void) => () => void
  onDeckId?: (deckId: string) => void
}

function extractSlugs(q: string): string {
  const m = q.match(/slides?:\s*([a-z0-9,\-\s]+?)(?:\.|$|\n)/i)
  return m ? m[1].trim() : ""
}

export function createSSEStream({ sessionId, subscribe, onDeckId }: BridgeOptions): ReadableStream {
  const encoder = new TextEncoder()

  return new ReadableStream({
    start(controller) {
      let subagentToolCallId: string | null = null
      let totalGroups = 0
      const subagentGroups = new Map<string, { group: number; slugs: string }>()
      const subagentQueryQueue: string[] = []

      function send(event: Record<string, unknown>) {
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)) } catch {}
      }

      function close() {
        unsubscribe()
        try { controller.close() } catch {}
      }

      const unsubscribe = subscribe((msg) => {
        // End turn from RPC response
        if (msg.id != null && msg.result) {
          const r = msg.result as Record<string, unknown>
          if (r.stopReason === "end_turn" || r.stopReason === "cancelled") { close(); return }
        }

        if (msg.method !== "session/update" && msg.method !== "_kiro.dev/session/update") return
        const params = msg.params as Record<string, unknown>
        const msgSessionId = params.sessionId as string
        const update = params.update as Record<string, unknown>
        if (!update) return
        const type = update.sessionUpdate as string

        // --- Subagent session (compose_slides progress) ---
        if (msgSessionId !== sessionId && subagentToolCallId) {
          let groupInfo = subagentGroups.get(msgSessionId)
          if (!groupInfo) {
            const idx = subagentGroups.size
            const slugs = subagentQueryQueue[idx] || `group ${idx + 1}`
            groupInfo = { group: idx + 1, slugs }
            subagentGroups.set(msgSessionId, groupInfo)
            send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: groupInfo.group, total_groups: totalGroups, slugs: groupInfo.slugs, status: "starting" } } })
          }
          const g = groupInfo
          if (type === "tool_call") {
            const title = (update.title || "") as string
            const toolName = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
            send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: g.group, slugs: g.slugs, tool: toolName, toolUseId: update.toolCallId } } })
          } else if (type === "tool_call_update") {
            const status = update.status as string
            if (status === "completed" || status === "error" || status === "failed") {
              send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: g.group, slugs: g.slugs, toolResult: update.toolCallId, toolStatus: status === "completed" ? "success" : "error" } } })
            }
          } else if (type === "turn_end" || type === "end_turn") {
            send({ toolStream: { toolUseId: subagentToolCallId, name: "compose_slides", data: { group: g.group, slugs: g.slugs, status: "done" } } })
          }
          return
        }

        if (msgSessionId !== sessionId) return

        // --- Main session events ---
        if (type === "agent_message_chunk") {
          const content = update.content as Record<string, unknown>
          if (content?.text) {
            send({ event: { contentBlockDelta: { delta: { text: content.text } } } })
          }
        }

        if (type === "tool_call" || type === "tool_call_chunk") {
          const toolCallId = update.toolCallId as string || ""
          const title = (update.title || update.name || "") as string
          let name = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title
          const input = (update.rawInput || update.input || {}) as Record<string, unknown>
          if (title === "Spawning agent crew" || name === "subagent") {
            subagentToolCallId = toolCallId
            subagentGroups.clear()
            // Extract group queries from use_subagent input
            // Cloud: input.content.queries[]  |  kiro-cli: input.stages[].prompt_template
            const content = (input.content as Record<string, unknown> | undefined) || input
            const queries = (content.queries as string[]) || []
            const stages = (input.stages as Array<Record<string, unknown>>) || []
            const groupTexts = queries.length > 0
              ? queries
              : stages.map((s) => (s.prompt_template as string) || (s.name as string) || "")
            totalGroups = groupTexts.length
            subagentQueryQueue.length = 0
            groupTexts.forEach((q: string) => subagentQueryQueue.push(extractSlugs(q)))
            // Build slide_groups for ComposeCard (Cloud format)
            const slideGroups = groupTexts.map((q: string) => ({
              slugs: extractSlugs(q).split(", ").map((s: string) => s.trim()).filter(Boolean),
              instruction: q,
            }))
            name = "compose_slides"
            if (type === "tool_call_chunk") {
              send({ toolStart: { toolUseId: toolCallId, name } })
            } else {
              send({ toolUse: { toolUseId: toolCallId, name, input: { slide_groups: slideGroups } } })
            }
            return
          }
          // tool_call_chunk: show card immediately; tool_call: update with input
          if (type === "tool_call_chunk") {
            send({ toolStart: { toolUseId: toolCallId, name } })
          } else {
            send({ toolUse: { toolUseId: toolCallId, name, input } })
          }
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
            if (result.deckId && onDeckId) onDeckId(result.deckId as string)
            send({ toolResult: { toolUseId: toolCallId, name: toolName, status: "success", content: JSON.stringify(result) } })
          }
        }

        if (type === "turn_end" || type === "end_turn") { close() }
      })
    },
  })
}
