// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Agent Adapter — server-side storage for agent configs.
 * Mirrors AgentSettingsDialog's AgentConfig interface.
 * Stores in mcp-local/.sdpm/acp-config.json.
 */

import fs from "fs"
import path from "path"

export interface AgentConfig {
  id: string
  displayName: string
  path: string
  args: string[]
  env: Record<string, string>
  subagentTool: string
  subagentInstruction: string
  restartOnNewChat: boolean
  subagentQueryField: "query" | "prompt"
}

const PRESETS: AgentConfig[] = [
  {
    id: "kiro-cli",
    displayName: "Kiro CLI",
    path: "kiro-cli",
    args: ["acp", "--agent", "sdpm-spec"],
    env: {},
    subagentTool: "use_subagent",
    subagentInstruction: "Use `use_subagent` with `subagents: [{\"query\": \"deck_id=... slides: slug1, slug2\", \"agent_name\": \"sdpm-composer\"}]` (max 4 parallel). ASCII-only queries.",
    restartOnNewChat: true,
    subagentQueryField: "query",
  },
  {
    id: "claude",
    displayName: "Claude Code",
    path: "claude",
    args: ["--acp"],
    env: {},
    subagentTool: "Task",
    subagentInstruction: "Use `Task` tool with `subagent_type: \"sdpm-composer\"`, `description: \"<brief>\"`, `prompt: \"deck_id=... slides: slug1, slug2\"`. Invoke multiple Task calls in parallel (max 4).",
    restartOnNewChat: false,
    subagentQueryField: "prompt",
  },
]

const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "mcp-local")
const CONFIG_DIR = path.join(MCP_LOCAL_DIR, ".sdpm")
const CONFIG_PATH = path.join(CONFIG_DIR, "acp-config.json")

interface StoredConfig {
  activeAgent: string
  agents: AgentConfig[]
}

function readConfig(): StoredConfig {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"))
    }
  } catch {}
  return { activeAgent: "kiro-cli", agents: PRESETS }
}

function writeConfig(config: StoredConfig): void {
  try {
    fs.mkdirSync(CONFIG_DIR, { recursive: true })
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + "\n", "utf-8")
  } catch {}
}

export function getAgents(): AgentConfig[] {
  return readConfig().agents
}

export function getActiveAgentId(): string {
  return readConfig().activeAgent
}

export function getActiveAgent(): AgentConfig {
  const config = readConfig()
  return config.agents.find(a => a.id === config.activeAgent) || config.agents[0] || PRESETS[0]
}

export function setActiveAgentId(id: string): void {
  const config = readConfig()
  config.activeAgent = id
  writeConfig(config)
}

export function saveAgents(agents: AgentConfig[]): void {
  const config = readConfig()
  config.agents = agents
  writeConfig(config)
}
