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

In this environment the call itself returns at once with a dispatch notice. The report
arrives later on its own, as the result of a `strands_manage_background_task` `get`: the
task's metadata JSON, then the report with the fields below. A `<composer_note group="N">`
in a message is a report from the composer of group N while it works.
When the direction changes while composers run, first correct the running work with
`message_composer` instead of cancelling and redoing it.

- `status`: `"completed"` / `"partial"` / `"failed"`
- `generated_slides`: slugs successfully written
- `failed_groups`: per-group failures with `slugs`, `instruction`, and `error` —
  on retry, call `compose_slides` again with ONLY these groups (reuse their
  slugs and instruction). Successfully generated slides do NOT need regeneration.
- `outline_check`: `{expected, missing, extra}` — if `missing` is non-empty,
  decide whether to retry the missing slugs or inform the user
- `summaries`: each composer's own completion summary
- `notice`: harness guidance for the current status — follow it

### Post-compose verification (this environment)

You cannot see the composers' own tool results (their `preview_files` stay
inside each composer). After the content call returns, call
`get_preview(deck_id, slugs=[...all slugs...])` yourself to see the
rendering — this is how you look before deciding whether any slide needs another composer.

For an HTML deck (`check_specs` returns `outputFormat: "html"`), `get_preview` returns the
PNGs the composers' browser checks made of the slides they wrote or changed; a slug with no
PNG yet comes back as a text line (its check was skipped or did not finish — see the
`output.html: Browser check …` warnings in the composers' `summaries`). Review through those
images, the `summaries` and the warnings in `build`, and never tell the user to open a local
`output.html` path.
