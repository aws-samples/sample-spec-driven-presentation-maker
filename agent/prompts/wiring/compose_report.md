## compose_slides — report format (this environment)

In this environment, dispatch composers via the `compose_slides` tool (dispatch
method 1 in your behavior instructions). It returns a JSON report:

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
`notice` and `summaries` in plain text, do NOT retry or call further tools,
and skip the Post-Compose Workflow (per your Cancellation instructions).
