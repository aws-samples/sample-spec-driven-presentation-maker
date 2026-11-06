# ACP fixtures

Raw agent-to-client JSON-RPC lines from kiro-cli 3.0.0 (macOS, 2026-11-05), one message per
line, in the order kiro-cli wrote them. `src/lib/local/acp-contract.test.ts` replays them
through the ACP process manager and the SSE bridge.

| File | Engine | Requests answered in order |
|---|---|---|
| `kiro-3.0.0-v2-turn.jsonl` | V2 (`kiro-cli acp --agent sdpm-orchestrator`) | initialize, session/new, session/prompt |
| `kiro-3.0.0-v3-turn.jsonl` | V3 (`kiro-cli acp --agent-engine v3`, agent definitions converted with `kiro-cli agent upgrade`) | initialize, session/new, session/prompt |
| `kiro-3.0.0-v2-compose.jsonl` | V2 (`kiro-cli acp --agent sdpm-orchestrator`), spike capture `s2_v2_gen` | initialize, session/new, session/prompt, session/prompt |

The two `turn` captures answer the prompt "Call the sdpm list_styles tool once, then reply with
only the number of styles" and end with `stopReason: end_turn`.

`kiro-3.0.0-v2-compose.jsonl` holds two turns of one session (main session `fa1545df…`). The
first is the same list_styles turn. In the second the orchestrator delegates to the
sdpm-composer sub-agent: a crew `tool_call_chunk` (title `subagent`) and `tool_call`
(`_meta.kiro.toolName: "subagent"`, one stage), `_kiro.dev/subagent/list_update`s, and the
composer's own session (`621f8fd1…`) with its text, thoughts, tool chunks and the
`list_templates` and `Summarizing` tool calls. Both turns end with `stopReason: end_turn`.

Trimmed from the captures (the shapes the bridge reads are unchanged):

- Dropped Kiro notifications that only describe the capturing machine: `_kiro.dev/commands/available`,
  `_kiro/steering/documents_changed`, `_kiro/progressive_context/items_changed`,
  `_kiro/tools/didChange`, `_kiro/governance/state`, `_kiro/powers/items_changed`,
  `_kiro/memory/syncStatus`, `_kiro/policy/changed`, `_kiro/customAgent/config_error`.
- Dropped `available_commands_update`, `config_option_update`, and `session_info_update`s that
  carry a context breakdown or steering list.
- Shortened lists in responses: `modes.availableModes` (sdpm modes, id and name only),
  `models.availableModels` (first 3), `configOptions` (mode and model, first 2 options);
  removed `agentCapabilities._meta.kiro.logging`.
- Replaced paths: the checkout with `/workspace/sdpm`, the home directory with `/home/user`,
  the deck root with `/tmp/sdpm/decks`.
