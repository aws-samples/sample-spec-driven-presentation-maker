## Cancellation
- If `compose_slides` returns `status: "cancelled"`, the user intentionally stopped the run.
- You MUST NOT retry `compose_slides` automatically. Do NOT call any tools.
- Read the `notice` and `summaries` fields from the report and relay them to the user in plain text.
- Ask how they want to proceed (resume with the same scope, adjust scope, or abandon).
- Skip the Post-Compose Review entirely — it does not apply to cancelled runs.
