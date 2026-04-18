/**
 * ACP Agent adapters — abstract over per-agent subagent/tool differences.
 *
 * ACP spec has no subagent concept; each agent implements it as a tool:
 *   kiro-cli  → use_subagent(subagents: [{query, agent_name}])
 *   claude    → Task(subagent_type, description, prompt)
 *   opencode  → task(description, prompt)  [and others similar to Task]
 *
 * Switch via VITE_SDPM_ACP_AGENT env (default: "kiro-cli").
 */

export interface AgentAdapter {
  /** Process spawn config. */
  command: string;
  args: string[];
  /** ACP tool name used to invoke sub-sessions for parallel compose. */
  subagentTool: string;
  /** SPEC prompt snippet explaining how to invoke subagents for THIS agent. */
  subagentInstruction: string;
  /** Extract per-subagent slug list from a tool-call's rawInput. */
  extractSubagentQueries: (rawInput: Record<string, unknown>) => string[];
  /** Restart process on new chat? (kiro-cli bug workaround) */
  restartOnNewChat: boolean;
  /** Enforce ASCII-only subagent queries? (kiro-cli UTF-8 bug) */
  asciiOnlyQueries: boolean;
}

const KIRO_CLI: AgentAdapter = {
  command: "kiro-cli",
  args: ["acp", "--agent", "sdpm-spec"],
  subagentTool: "use_subagent",
  subagentInstruction:
    'Use `use_subagent` with `subagents: [{"query": "deck_id=... slides: slug1, slug2", "agent_name": "sdpm-composer"}, ...]` (max 4 parallel). ASCII-only queries.',
  extractSubagentQueries: (raw) => {
    const subs = raw?.subagents as { query?: string }[] | undefined;
    return subs?.map((s) => s?.query || "") || [];
  },
  restartOnNewChat: true,
  asciiOnlyQueries: true,
};

const CLAUDE_CODE: AgentAdapter = {
  command: "claude",
  args: ["--acp"],
  subagentTool: "Task",
  subagentInstruction:
    'Use `Task` tool with `subagent_type: "sdpm-composer"`, `description: "<brief>"`, `prompt: "deck_id=... slides: slug1, slug2"`. Invoke multiple Task calls in parallel (max 4).',
  extractSubagentQueries: (raw) => {
    const p = raw?.prompt as string | undefined;
    return p ? [p] : [];
  },
  restartOnNewChat: false,
  asciiOnlyQueries: false,
};

const OPENCODE: AgentAdapter = {
  command: "opencode",
  args: ["acp"],
  subagentTool: "task",
  subagentInstruction:
    'Use `task` tool with `description: "<brief>"`, `prompt: "deck_id=... slides: slug1, slug2"`. Invoke multiple task calls in parallel.',
  extractSubagentQueries: (raw) => {
    const p = raw?.prompt as string | undefined;
    return p ? [p] : [];
  },
  restartOnNewChat: false,
  asciiOnlyQueries: false,
};

const ADAPTERS: Record<string, AgentAdapter> = {
  "kiro-cli": KIRO_CLI,
  claude: CLAUDE_CODE,
  opencode: OPENCODE,
};

export function getAgentAdapter(): AgentAdapter {
  const name = (import.meta.env.VITE_SDPM_ACP_AGENT as string) || "kiro-cli";
  return ADAPTERS[name] || KIRO_CLI;
}
