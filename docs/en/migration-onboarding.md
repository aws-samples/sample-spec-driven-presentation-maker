# Migration: one installer, one launcher

Applies if you set SDPM up before the installer existed — through a Claude Code plugin, a
Codex plugin, a Kiro Power, `make install-kiro`, the `skills/` directory, or a `uvx …
sdpm-mcp` client entry. All of those are gone. The MCP server is the complete product;
one local installation serves every client and the browser Web UI.

## What to do

1. Install:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash
   ```
   (Windows: `irm …/install.ps1 | iex`.) Say yes when it offers to register your clients.
2. Remove the old entry from each client you had connected:

   | You had | Remove with |
   |---|---|
   | Claude Code plugin `sdpm@sdpm` | `/plugin uninstall sdpm@sdpm` |
   | Claude Code `claude mcp add … uvx …` | `claude mcp remove sdpm` (then `sdpm register claude-code`) |
   | Codex plugin | remove it in the ChatGPT desktop app; `codex mcp remove sdpm` if you added the uvx entry |
   | Kiro CLI `make install-kiro` (agent `sdpm-composer`, `mcp.json` entry pointing at a checkout) | `kiro-cli mcp remove --scope global --name sdpm`; delete `~/.kiro/agents/sdpm-composer.json`; then `sdpm register kiro-cli` |
   | Kiro IDE Power | uninstall the Power in Kiro IDE; `sdpm register kiro-cli` covers Kiro IDE too |
   | Cursor / VS Code `uvx` entry | delete the `sdpm` entry from `~/.cursor/mcp.json` / the VS Code MCP user configuration, then `sdpm register` |
   | A `skills/sdpm-*` directory copied into an agent | delete it — the `sdpm-*` prompts replaced the skills |
   | A checkout you cloned only to run the server | delete it; `~/.sdpm/checkout` is the one that is updated |

3. Check with `sdpm` — it lists the clients it can see and whether SDPM is registered.

## Why

- **One installation.** Coding agents and the Web UI are not exclusive; the `uvx` path gave a
  user who also installed the Web UI two copies of the server with two versions and two
  asset directories.
- **Nothing on the agent side.** Since the `start_*` entry tools and the `sdpm-*` prompts,
  a plugin only wrapped one MCP server line in a vendor manifest. `sdpm register` writes
  that line through each client's own CLI instead.
- **Absolute paths.** GUI clients started from the Dock or Start Menu do not inherit your
  shell `PATH`; the generated configuration points at `uv` and the checkout directly.
- **No PyPI, no `uvx`.** The repository cannot publish to PyPI; `uvx --from git+https://…`
  followed `main` yet was frozen by uv's cache.

## What did not change

Tool names, the role documents, the `sdpm-*` prompts, deck layouts, the remote (AWS) MCP
server, and the Claude Desktop `.mcpb` bundle.
