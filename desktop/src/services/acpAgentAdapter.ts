/**
 * ACP Agent adapter — reads active agent config from localStorage
 * (set via AgentSettingsDialog). Falls back to kiro-cli defaults.
 */

export interface AgentAdapter {
  command: string;
  args: string[];
  subagentTool: string;
  subagentInstruction: string;
  extractSubagentQueries: (rawInput: Record<string, unknown>) => string[];
  restartOnNewChat: boolean;
  asciiOnlyQueries: boolean;
}

interface StoredAgent {
  id: string;
  displayName: string;
  path: string;
  args: string[];
  subagentTool: string;
  subagentInstruction: string;
  restartOnNewChat: boolean;
  subagentQueryField: "query" | "prompt";
}

const DEFAULT: AgentAdapter = {
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

function makeExtractor(field: "query" | "prompt"): AgentAdapter["extractSubagentQueries"] {
  if (field === "query") {
    return (raw) => {
      const subs = raw?.subagents as { query?: string }[] | undefined;
      return subs?.map((s) => s?.query || "") || [];
    };
  }
  // "prompt" field — a single subagent per call; raw itself has prompt
  return (raw) => {
    const p = raw?.prompt as string | undefined;
    return p ? [p] : [];
  };
}

export function getAgentAdapter(): AgentAdapter {
  try {
    const stored = localStorage.getItem("sdpm-acp-agents");
    const activeId = localStorage.getItem("sdpm-acp-active") || "kiro-cli";
    if (stored) {
      const agents: StoredAgent[] = JSON.parse(stored);
      const a = agents.find((x) => x.id === activeId) || agents[0];
      if (a) {
        return {
          command: a.path,
          args: a.args,
          subagentTool: a.subagentTool,
          subagentInstruction: a.subagentInstruction,
          extractSubagentQueries: makeExtractor(a.subagentQueryField),
          restartOnNewChat: a.restartOnNewChat,
          asciiOnlyQueries: a.id === "kiro-cli",
        };
      }
    }
  } catch { /* ignore */ }
  return DEFAULT;
}
