// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ACP Agent Adapter — reads the agent config for the ACP process manager.
 * Stored in servers/local/.sdpm/acp-config.json (kiro-cli preset when missing).
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
    args: ["acp", "--agent", "sdpm-orchestrator"],
    env: {},
    subagentTool: "use_subagent",
    subagentInstruction: "Use `use_subagent` with agent_name `sdpm-composer` and pass the orchestrator's delegation prompt unchanged as `query`.",
    restartOnNewChat: true,
    subagentQueryField: "query",
  },
]

const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "servers", "local")
// SDPM_ACP_CONFIG_DIR: override for tests (E2E points this at a sandbox
// so the stub agent config never touches the developer's real one)
const CONFIG_DIR = process.env.SDPM_ACP_CONFIG_DIR || path.join(MCP_LOCAL_DIR, ".sdpm")
const CONFIG_PATH = path.join(CONFIG_DIR, "acp-config.json")

interface StoredConfig {
  activeAgent: string
  agents: AgentConfig[]
}

function readConfig(): StoredConfig {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"))
      return { activeAgent: raw.activeAgent || "kiro-cli", agents: raw.agents || PRESETS }
    }
  } catch {}
  return { activeAgent: "kiro-cli", agents: PRESETS }
}

export function getActiveAgent(): AgentConfig {
  const config = readConfig()
  return config.agents.find(a => a.id === config.activeAgent) || config.agents[0] || PRESETS[0]
}
