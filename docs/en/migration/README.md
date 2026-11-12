# Migration guides

Read this page if you used SDPM before and something stopped working after an update.
New users can skip it.

## Which guide do I need?

Newest first:

| You set SDPM up with | Read |
|---|---|
| A Claude Code or Codex plugin, the Kiro Power, `make install-kiro`, the `skills/` directory, or a `uvx … sdpm-mcp` client entry | [One installer, one launcher](onboarding.md) |
| v0.5 (`start_presentation(mode=…)`, `personas/`, the `sdpm-vibe` / `sdpm-spec` skills) | [Role workflows](role-workflows.md) |
| v0.4 (`skill/`, `mcp-local/`, `mcp-server/`) | [Migrating to v0.5](v0.5.md) |

For changes newer than these guides, see the [CHANGELOG](../../../CHANGELOG.md).

## Setups that no longer exist

The installer replaced every earlier way of connecting SDPM to an AI agent. These setups
are gone:

- the Claude Code and Codex plugins
- the Kiro Power
- `make install-kiro`
- the `skills/` directory
- client entries that start the server with `uvx … sdpm-mcp`

Install once with the installer, then remove the old entry from each client. The
[onboarding guide](onboarding.md) has a table with the removal step for each one.

Kiro CLI users: run `sdpm register kiro-cli`. It finds three kinds of leftovers of the old
setup and offers to remove them:

- the generated agent `~/.kiro/agents/sdpm-composer.json`, which can no longer start
- the `~/.kiro/skills/sdpm-*` links (or copied directories) of the old skills
- an `sdpm` entry in the global `~/.kiro/settings/mcp.json`, which loads the tools into every
  Kiro CLI session

Tool names, the `sdpm-*` prompts and deck files did not change. Existing decks keep working.
