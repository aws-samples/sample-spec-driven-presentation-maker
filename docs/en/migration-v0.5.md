# Migrating to v0.5

v0.5 is a breaking release focused on architecture cleanup. No slide JSON
schema changes — **existing decks keep working** locally and on the cloud stack.

## What changed

| v0.4 | v0.5 |
|---|---|
| `skill/` | `sdpm/` (engine + knowledge + references + templates) |
| `mcp-local/` | `servers/local/` |
| `mcp-server/` | `servers/remote/` |
| `skills/sdpm-vibe`, `skills/sdpm-spec` (SKILL.md) | Removed — mode behavior is served by the MCP server via `start_presentation(mode=...)` |
| `agents/sdpm-composer.md` | `clients/claude-code/agents/sdpm-composer.md` (thin; behavior in `personas/composer.md`) |
| `mcp-local/acp-agent-prompts/*.md` | `personas/*.md` (single source for all mode behaviors) |
| Per-client behavior copies | `personas/` is the only place behavior text lives |

## Migration steps by environment

### Claude Code plugin

```
/plugin uninstall sdpm@sdpm   # optional but recommended (clears cached skills)
/plugin install sdpm@sdpm     # re-install picks up the new layout
```

The plugin no longer installs skills. Slide requests trigger the MCP server's
`start_presentation` tool instead. The composer sub-agent is still registered
(`sdpm:sdpm-composer`).

### Kiro CLI

```bash
git pull
make install-kiro
```

The installer removes dangling skill symlinks from pre-v0.5 installs
(`~/.kiro/skills/sdpm-*`), removes the legacy generated composer agent config
(composer sub-agents are now self-spawned — no agent file is needed), and
re-registers the MCP server path (`servers/local`).

### Claude Desktop / other MCP clients

Update the server path in your MCP config:

```diff
- "args": ["run", "--directory", "<checkout>/mcp-local", "python", "server.py"]
+ "args": ["run", "--directory", "<checkout>/servers/local", "python", "server.py"]
```

There is no separate `server_with_instruction.py` anymore — `server.py` serves
both Server Instructions and the `start_presentation` tool.

### pip install of the engine

```diff
- pip install "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=skill"
+ pip install "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=sdpm"
```

### AWS cloud stack

Redeploy from the new checkout — all repository references are build-time
(Docker COPY paths, CDK assets), so a normal deploy rebuilds everything
consistently. CDK logical IDs are unchanged: no resource replacement, and
S3/DynamoDB data (decks, templates, styles) is untouched.

```bash
AWS_DEFAULT_REGION=<region> bash scripts/deploy_webui.sh
```

## New in v0.5

- `start_presentation(mode="vibe"|"spec"|"style"|"composer")` — mode behavior
  delivered through the tool contract to **any** MCP client. Clients without
  a sub-agent mechanism (e.g. Claude Desktop) now work end-to-end: the
  orchestrator persona falls back to sequential composition.
- `sdpm.engine` / `sdpm.knowledge` split — the engine is pure json↔pptx;
  knowledge (references, assets) is a peer subpackage.
- `sdpm.tools` — every MCP tool defined once, both servers are thin binds.
