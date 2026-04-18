// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentSettingsDialog — lets users register custom ACP agents
 * (Obsidian Agent Client plugin-style configuration).
 */
"use client"

import { useState, useEffect } from "react"
import { X, Plus, Trash2 } from "lucide-react"

export interface AgentConfig {
  id: string
  displayName: string
  path: string        // executable command (e.g. "kiro-cli", "/usr/local/bin/claude")
  args: string[]      // ["acp"] or ["acp", "--agent", "sdpm-spec"]
  env?: Record<string, string>
  subagentTool: string
  subagentInstruction: string
  restartOnNewChat: boolean
  subagentQueryField: "query" | "prompt"  // How to extract slug list from subagent call
}

const PRESETS: AgentConfig[] = [
  {
    id: "kiro-cli",
    displayName: "Kiro CLI",
    path: "kiro-cli",
    args: ["acp", "--agent", "sdpm-spec"],
    subagentTool: "use_subagent",
    subagentInstruction: 'Use `use_subagent` with `subagents: [{"query": "deck_id=... slides: slug1, slug2", "agent_name": "sdpm-composer"}, ...]` (max 4 parallel). ASCII-only queries.',
    restartOnNewChat: true,
    subagentQueryField: "query",
  },
  {
    id: "claude",
    displayName: "Claude Code",
    path: "claude",
    args: ["--acp"],
    subagentTool: "Task",
    subagentInstruction: 'Use `Task` tool with `subagent_type: "sdpm-composer"`, `description: "<brief>"`, `prompt: "deck_id=... slides: slug1, slug2"`. Invoke multiple Task calls in parallel (max 4).',
    restartOnNewChat: false,
    subagentQueryField: "prompt",
  },
]

const STORAGE_KEY = "sdpm-acp-agents"
const ACTIVE_KEY = "sdpm-acp-active"

export function loadAgents(): AgentConfig[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return PRESETS
}

export function saveAgents(agents: AgentConfig[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(agents))
}

export function getActiveAgentId(): string {
  return localStorage.getItem(ACTIVE_KEY) || "kiro-cli"
}

export function setActiveAgentId(id: string) {
  localStorage.setItem(ACTIVE_KEY, id)
}

export function getActiveAgent(): AgentConfig {
  const agents = loadAgents()
  const id = getActiveAgentId()
  return agents.find(a => a.id === id) || agents[0] || PRESETS[0]
}

interface Props {
  open: boolean
  onClose: () => void
}

export function AgentSettingsDialog({ open, onClose }: Props) {
  const [agents, setAgents] = useState<AgentConfig[]>([])
  const [activeId, setActiveId] = useState("")

  useEffect(() => {
    if (!open) return
    setAgents(loadAgents())
    setActiveId(getActiveAgentId())
  }, [open])

  if (!open) return null

  const update = (idx: number, patch: Partial<AgentConfig>) => {
    const next = [...agents]
    next[idx] = { ...next[idx], ...patch }
    setAgents(next)
  }

  const remove = (idx: number) => {
    const next = agents.filter((_, i) => i !== idx)
    setAgents(next)
  }

  const addCustom = () => {
    setAgents([...agents, {
      id: `custom-${Date.now()}`,
      displayName: "Custom Agent",
      path: "",
      args: [],
      subagentTool: "task",
      subagentInstruction: "Use task tool to delegate slides.",
      restartOnNewChat: false,
      subagentQueryField: "prompt",
    }])
  }

  const save = () => {
    saveAgents(agents)
    setActiveAgentId(activeId)
    onClose()
    // Prompt user to restart or auto-restart ACP
    window.location.reload()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-background border border-border rounded-lg w-full max-w-2xl max-h-[80vh] overflow-auto p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">ACP Agents</h2>
          <button onClick={onClose} className="p-1 hover:bg-accent rounded"><X className="h-4 w-4" /></button>
        </div>

        <div className="space-y-3">
          {agents.map((a, i) => (
            <div key={a.id} className="border border-border rounded-md p-3 space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={activeId === a.id}
                  onChange={() => setActiveId(a.id)}
                />
                <input
                  className="flex-1 bg-transparent text-sm font-medium border-b border-border focus:outline-none focus:border-brand-teal"
                  value={a.displayName}
                  onChange={e => update(i, { displayName: e.target.value })}
                  placeholder="Display Name"
                />
                <button onClick={() => remove(i)} className="p-1 hover:bg-destructive/10 rounded text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
              <div className="grid grid-cols-[100px_1fr] gap-x-2 gap-y-1 text-xs">
                <label className="text-foreground-muted self-center">Agent ID</label>
                <input className="bg-transparent border border-border rounded px-2 py-1" value={a.id} onChange={e => update(i, { id: e.target.value })} />

                <label className="text-foreground-muted self-center">Path</label>
                <input className="bg-transparent border border-border rounded px-2 py-1" value={a.path} onChange={e => update(i, { path: e.target.value })} placeholder="kiro-cli or /usr/local/bin/claude" />

                <label className="text-foreground-muted self-center">Arguments</label>
                <input className="bg-transparent border border-border rounded px-2 py-1" value={a.args.join(" ")} onChange={e => update(i, { args: e.target.value.split(" ").filter(Boolean) })} placeholder="acp --agent sdpm-spec" />

                <label className="text-foreground-muted self-center">Subagent Tool</label>
                <input className="bg-transparent border border-border rounded px-2 py-1" value={a.subagentTool} onChange={e => update(i, { subagentTool: e.target.value })} placeholder="use_subagent / Task / task" />

                <label className="text-foreground-muted self-center">Query Field</label>
                <select className="bg-transparent border border-border rounded px-2 py-1" value={a.subagentQueryField} onChange={e => update(i, { subagentQueryField: e.target.value as "query" | "prompt" })}>
                  <option value="query">query (kiro-cli)</option>
                  <option value="prompt">prompt (claude/opencode)</option>
                </select>

                <label className="text-foreground-muted self-center">Restart on new chat</label>
                <input type="checkbox" className="justify-self-start mt-1.5" checked={a.restartOnNewChat} onChange={e => update(i, { restartOnNewChat: e.target.checked })} />

                <label className="text-foreground-muted self-start pt-1">Prompt Inject</label>
                <textarea className="bg-transparent border border-border rounded px-2 py-1 font-mono text-[11px]" rows={3} value={a.subagentInstruction} onChange={e => update(i, { subagentInstruction: e.target.value })} />
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between mt-4">
          <button onClick={addCustom} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border hover:bg-accent">
            <Plus className="h-3.5 w-3.5" /> Add Agent
          </button>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-xs rounded hover:bg-accent">Cancel</button>
            <button onClick={save} className="px-3 py-1.5 text-xs rounded bg-brand-teal text-white hover:bg-brand-teal/80">Save & Restart</button>
          </div>
        </div>
      </div>
    </div>
  )
}
