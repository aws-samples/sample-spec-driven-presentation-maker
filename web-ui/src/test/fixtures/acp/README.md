# ACP fixtures

Raw agent-to-client JSON-RPC lines from kiro-cli 3.0.0 (macOS, 2026-11-05), one message per
line, in the order kiro-cli wrote them. `src/lib/local/acp-contract.test.ts` replays them
through the ACP process manager, the engine adapters and the SSE bridge.

A line `{"client": {"id": N, "method": "…"}}` is not kiro-cli's: it marks where the capturing
client sent its request `N`. The replay answers each request of the client under test with the
lines from the matching marker to the next one (the answer's id rewritten), so the lines kiro-cli
sent after an answer and before the client's next request (V3's MCP readiness) arrive with that
answer. The client must send the same methods in the same order; the replay fails the test
otherwise.

| File | Engine, source | Client requests, in order |
|---|---|---|
| `kiro-3.0.0-v2-turn.jsonl` | V2 (`kiro-cli acp --agent sdpm-orchestrator`) | initialize, session/new, session/prompt |
| `kiro-3.0.0-v3-turn.jsonl` | V3 (`kiro-cli acp --agent-engine v3`, agent definitions converted with `kiro-cli agent upgrade`) | initialize, session/new, session/prompt |
| `kiro-3.0.0-v2-compose.jsonl` | V2, spike capture `s2_v2_gen` | initialize, session/new, session/prompt, session/prompt |
| `kiro-3.0.0-v3-compose.jsonl` | V3, `s2_v3_gen` (keeps `config_option_update`, mode and model only) | initialize, session/new, session/prompt, session/prompt |
| `kiro-3.0.0-v3-parallel-compose.jsonl` | V3, `s7_v3_parallel_subtasks` | initialize, session/new, session/prompt |
| `kiro-3.0.0-v2-mcp-failed.jsonl` | V2, `s6d_v2_bad_mcp` (an MCP command that exits) | initialize, session/new |
| `kiro-3.0.0-v3-mcp-failed.jsonl` | V3, `s6d_v3_bad_mcp` | initialize, session/new |
| `kiro-3.0.0-v2-agent-not-found.jsonl` | V2 started with `--agent sdpm-spec`, `s1_v2_stale_sdpm_spec` | initialize, session/new |
| `kiro-3.0.0-v3-vibe-fallback.jsonl` | V3 with the V2-form catalog, `s1_v3_catalog` | initialize, session/new |
| `kiro-3.0.0-v3-auth-required.jsonl` | V3 with an empty `HOME`, `s3_v3_fake_HOME` | initialize, session/new (error -32000) |
| `kiro-3.0.0-v2-new-mcp-first.jsonl` | V2, `s6a_v2_prompt_without_mcp_wait` | initialize, session/new, session/prompt |
| `kiro-3.0.0-v2-load-not-found.jsonl` | V2 loading a V3 id, `s4_5_v2_load_v3sid` (its second load cut) | initialize, session/new, session/load (Session not found) |
| `kiro-3.0.0-v3-load-imported.jsonl` | V3 loading a V2 session, `s4_2_v3_load_v2uuid` (session/list cut) | initialize, session/load, session/prompt |
| `kiro-3.0.0-v3-load-created.jsonl` | V3 loading an id it does not have, `s4_4_v3_load_known_unknown` (only that load kept) | initialize, session/load |
| `kiro-3.0.0-v3-load-setmode.jsonl` | V3 loading a fork copied from a `vibe` session, `s6b_2_v3_load_fork_setmode` | initialize, session/load, session/set_mode, session/prompt, session/prompt |
| `kiro-3.0.0-v3-load-subtask-style.jsonl` | V3, the same fork without set_mode, `s6b_2_v3_load_fork_modeid` (read through the V3 translator alone) | initialize, session/load, session/prompt, session/prompt |
| `kiro-3.0.0-v2-setmode-mcp.jsonl` | V2 loading an `sdpm-style` session, `s9_v2_2_load_setmode` | initialize, session/new, session/load, session/set_mode |
| `kiro-3.0.0-v3-setmode-mcp.jsonl` | V3, the same, `s9_v3_2_load_setmode` | initialize, session/load, session/set_mode |
| `kiro-3.0.0-v3-permission.jsonl` | V3 with `sdpm/list_styles` not allowed, `s2_v3_perm` (two permission requests) | initialize, session/new, session/prompt, session/prompt |
| `kiro-3.1.0-v3-list.jsonl` | V3 listing its sessions with workflow sessions excluded, `s13_3_v3_list_fork` (one `vibe` session) | initialize, session/list |
| `kiro-3.1.0-v3-fork.jsonl` | V3 forking that `vibe` session into servers/local in the sdpm-orchestrator mode, the same capture | initialize, session/fork, session/load, session/prompt |
| `kiro-3.1.0-v3-fork-v2.jsonl` | V3 forking a V2 session it had not imported, the same capture | initialize, session/fork, session/load, session/prompt |
| `kiro-3.1.0-v3-model-effort.jsonl` | V3, `s14c_1_v3_new_model_effort` (model Claude Haiku 5.5, then effort low) | initialize, session/new, session/set_config_option (model), session/set_config_option (effortLevel), session/prompt |
| `kiro-3.1.0-v3-model-load.jsonl` | V3 loading that session in a new process, `s14c_2_v3_load` | initialize, session/load |
| `kiro-3.1.0-v2-set-model.jsonl` | V2, `s14c_3_v2_set_model` (model claude-haiku-4.5) | initialize, session/new, session/set_model, session/prompt |
| `kiro-3.1.0-v3-async-compose-orchestrator.jsonl` | V3 orchestrator with `SDPM_LOCAL_COMPOSE=1`, web-2 spike: a 2-slide deck dispatched with one `compose_slides` (2 groups), a user turn during compose, a `message_composer` to group 1, the `<compose_result>` wake | initialize, session/new, session/prompt, session/prompt, session/prompt, session/prompt |
| `kiro-3.1.0-v3-async-compose-composer.jsonl` | V3 composer of group 1 on its own kiro-cli (`modeId: sdpm-composer`, no `SDPM_LOCAL_COMPOSE`), the same spike: steered once (`steering_queued`, `steering_injected`), then closed and deleted | initialize, session/new, session/set_config_option (model), session/prompt, _session/steer, session/close, session/delete |
| `kiro-3.1.0-v3-async-compose-composer-2.jsonl` | V3 composer of group 2, the same spike (no steer) | initialize, session/new, session/set_config_option (model), session/prompt, session/close, session/delete |
| `kiro-3.1.0-v2-async-compose-orchestrator.jsonl` | V2 (`--agent sdpm-orchestrator`), the same flow | initialize, session/new, session/prompt, session/prompt, session/prompt, session/prompt |
| `kiro-3.1.0-v2-async-compose-composer.jsonl` | V2 composer of group 1 (`--agent sdpm-composer`), steered once (`AgentExecutionSteeringInjected`) | initialize, session/new, session/set_model, session/prompt, _session/steer |
| `kiro-3.1.0-v2-async-compose-composer-2.jsonl` | V2 composer of group 2 (no steer) | initialize, session/new, session/set_model, session/prompt |

The `kiro-3.1.0-*` files are kiro-cli 3.1.0 (KAS 0.66.70, 2026-11-07) captures with a
temporary `KIRO_HOME`. In the list and fork captures, the sources remembered a codeword (MANGO
on V3, GUAVA on V2) that each fork's prompt asks for; each fork's load answers
`_meta.parentSessionId` = the source. In the model captures (`v3-model-*`, `v2-set-model`, spike
S14c), the `config_option_update`s and `configOptions` keep `mode` (sdpm modes), `model`
(4 values: `auto`, `claude-haiku-5.5`, `claude-haiku-4.5` and the `[Internal]` `grok-4.7`, with
`_meta.kiro` `rateMultiplier`, `hasEffort`, `effortLevels`, `defaultEffortLevel`), `effortLevel`
and `thinking`; V2's `models.availableModels` keeps `auto`, `claude-haiku-5.5`, `claude-haiku-4.5`.

The `async-compose` files are kiro-cli 3.1.0 (2026-11-08) captures of the web-2 spike
(`async_compose_spike.py`): one kiro-cli for the orchestrator and one per composer group, each in a
temporary `KIRO_HOME` and `HOME`. The orchestrator's `compose_slides` and `message_composer` calls
carry their whole input on the first `tool_call` (V3 `rawInput.arguments`, V2 `rawInput`); their
completed updates carry no tool name (V3) or the title `Running: @sdpm/…` (V2). Tool inputs and
outputs over 1 500 characters are cut, image bytes and thought chunks dropped. Group 1's composer
capture answers its prompt only after the steer marker, group 2's at once.

The two `turn` captures answer the prompt "Call the sdpm list_styles tool once, then reply with
only the number of styles" and end with `stopReason: end_turn`.

`kiro-3.0.0-v2-compose.jsonl` holds two turns of one session (main session `fa1545df…`). The
first is the same list_styles turn. In the second the orchestrator delegates to the
sdpm-composer sub-agent: a crew `tool_call_chunk` (title `subagent`) and `tool_call`
(`_meta.kiro.toolName: "subagent"`, one stage), `_kiro.dev/subagent/list_update`s, and the
composer's own session (`621f8fd1…`) with its text, thoughts, tool chunks and the
`list_templates` and `Summarizing` tool calls. Both turns end with `stopReason: end_turn`.
`kiro-3.0.0-v3-compose.jsonl` is the same two turns on V3: the delegation is an `agent-subtask`
tool call of the main session, and the composer's updates carry its `agentSubtaskId`.

The spike client (like the earlier probe of the two `turn` captures) waited for the sdpm server
before its first prompt, as this app does.

Trimmed from the captures (the shapes the bridge reads are unchanged):

- Dropped Kiro notifications that only describe the capturing machine: `_kiro.dev/commands/available`,
  `_kiro/steering/documents_changed`, `_kiro/progressive_context/items_changed`,
  `_kiro/tools/didChange`, `_kiro/governance/state`, `_kiro/powers/items_changed`,
  `_kiro/memory/syncStatus`, `_kiro/policy/changed`, `_kiro/customAgent/config_error`.
- Dropped `available_commands_update`, `config_option_update` (except where noted), and
  `session_info_update`s that carry a context breakdown or steering list.
- Shortened lists in responses: `modes.availableModes` (sdpm modes, id and name only),
  `models.availableModels` (first 3), `configOptions` (mode and model, first 2 options);
  removed `agentCapabilities._meta.kiro.logging`, and the `tools` and `_meta` of each server in
  `_kiro/mcp/status`.
- Replaced paths: the checkout with `/workspace/sdpm`, the home directory with `/home/user`,
  `KIRO_HOME` with `/home/user/.kiro`, the deck root with `/tmp/sdpm/decks`.
- Dropped the client's answers to kiro-cli's requests (the replay records this client's own).
