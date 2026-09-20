# Migration: role workflows (replacing personas and start_presentation)

This release consolidates mode behavior into role documents and renames tool/CLI
surfaces to match. No slide JSON schema changes — **existing decks keep
working** locally and on the cloud stack.

## What changed

| v0.5 | this release |
|---|---|
| `start_presentation(mode="vibe"\|"spec"\|"style"\|"composer"\|"translate")` | Removed — call `read_workflows(["orchestrator"\|"composer"\|"style"\|"translate"])` instead |
| `personas/*.md` | Removed — role + procedure text now lives in `sdpm/references/workflows/{orchestrator,composer,style,translate}.md` |
| `skills/sdpm-vibe`, `skills/sdpm-spec` | Replaced by `skills/sdpm-create` (dialogue depth follows your own wording, not a fixed mode) |
| — | `skills/sdpm-composer` added (dispatched by the orchestrator, not picked by users) |
| `sdpm/references/workflows/slide-json-spec.md` | Moved to `sdpm/references/spec/slide-json-spec.md` (still readable via `read_workflows`) |
| `sdpm/references/workflows/create-new-4-hand-edit-sync.md` | Moved to `sdpm/references/guides/hand-edit-sync.md` |
| `sdpm/references/examples/patterns.pptx` + `search-patterns` CLI | Removed, no replacement — the technique audit found no measurable output benefit; invest in style HTML instead |

### CLI subcommand renames (`sdpm/scripts/pptx_builder.py`)

| Old | New |
|---|---|
| `generate` | `generate_pptx` |
| `examples` | `read_examples` |
| `workflows` | `read_workflows` |
| `guides` | `read_guides` |
| `analyze-template` | `analyze_template` |
| `search-assets` | `search_assets` |
| `list-templates` | `list_templates` |
| `init` | `init_presentation` |
| `code-block` | `code_to_slide` |
| `layout` | `arch_diagram` |
| `diff` | `diff_pptx` |
| `search-patterns` | Removed |

`grid`, `preview`, `measure`, `image-size`, `list-asset-sources` are unchanged.
No aliases for the old names — update any scripts or docs that call them.

## Migration steps by environment

### Claude Code plugin

```
/plugin uninstall sdpm@sdpm   # optional but recommended (clears cached skills)
/plugin install sdpm@sdpm     # re-install picks up sdpm-create / sdpm-composer
```

### Kiro CLI

```bash
git pull
make install-kiro
```

The installer replaces the old `sdpm-vibe` / `sdpm-spec` skill symlinks with
`sdpm-create`, and regenerates the `sdpm-composer` agent to point at the new
`sdpm-composer` skill.

### Claude Desktop / other MCP clients

No config change — the server path (`servers/local`) is unchanged. If your
own prompts or automation call `start_presentation`, switch them to
`read_workflows(["orchestrator"])` (or `"composer"` / `"style"` / `"translate"`).

### AWS cloud stack

Redeploy from the new checkout — all repository references are build-time
(Docker COPY paths, CDK assets), so a normal deploy rebuilds everything
consistently. CDK logical IDs are unchanged: no resource replacement, and
S3/DynamoDB data (decks, templates, styles) is untouched.

```bash
AWS_DEFAULT_REGION=<region> bash scripts/deploy_webui.sh
```

### GenU AgentBuilder integration

Drop the `personas/` copy step — see the updated
[Connecting Agents](add-to-gateway.md#step-1-copy-sdpm-files-into-the-genu-agentcore-runtime-directory)
instructions; role documents now ship inside `sdpm/references/workflows/`.

## Web UI behaviour

Nothing to migrate: the Spec / Vibe selector and the "Parallel agents" setting keep
their behaviour. They now reach the orchestrator as a one-line `Interaction mode:
dialogue|fast` token (defined in `workflows/orchestrator.md`) instead of selecting a
persona file.
