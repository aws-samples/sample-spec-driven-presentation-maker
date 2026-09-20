## compose_slides — dispatch and report (this environment)

Composers are dispatched with `compose_slides(deck_id, slide_groups=[{slugs, instruction}])`.
It runs exactly the groups you pass, once, in parallel — nothing else happens inside it. Each
pass of your workflow is therefore one call, and `instruction` is the `task_instruction` the
workflow refers to:

- layout — one group, all slugs, `instruction: "Layout pass."`
- content — several groups
- a change to one slide — one group with that slug

Before dispatch, `compose_slides` validates deck.json and outline.md and returns `status: "error"` with `errors` when validation fails.

It returns a JSON report:

- `status`: `"completed"` / `"partial"` / `"failed"` / `"cancelled"`
- `generated_slides`: slugs successfully written
- `failed_groups`: per-group failures with `slugs`, `instruction`, and `error` —
  on retry, call `compose_slides` again with ONLY these groups (reuse their
  slugs and instruction). Successfully generated slides do NOT need regeneration.
- `outline_check`: `{expected, missing, extra}` — if `missing` is non-empty,
  decide whether to retry the missing slugs or inform the user
- `summaries`: each composer's own completion summary
- `notice`: harness guidance for the current status — follow it

`status: "cancelled"` means the user intentionally stopped the run: relay
`notice` and `summaries` in plain text, do NOT retry or call further tools.

### Post-compose verification (this environment)

You cannot see the composers' own tool results (their `preview_files` stay
inside each composer). After the content call returns, call
`get_preview(deck_id, slugs=[...all slugs...])` yourself to see the
rendering — this is how you look before deciding whether any slide needs another composer.
