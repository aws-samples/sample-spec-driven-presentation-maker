# Summary

<!-- What does this PR change, and why? -->

## Checklist

- [ ] `make all` passes (ruff + pytest)
- [ ] `ash scan --mode local --fail-on-findings` passes (see CONTRIBUTING.md)
- [ ] Docs updated if behavior/paths changed (README, docs/en, AGENTS.md)
- [ ] `CHANGELOG.md` `[Unreleased]` updated for user-facing changes
- [ ] Commit messages follow Conventional Commits

## Testing

<!-- How was this verified? Unit tests, manual slide generation, deploy? -->

## Boundaries touched

<!-- Delete rows that don't apply -->
- [ ] `sdpm/templates/*.pptx` (base templates — normally do not modify)
- [ ] `sdpm/references/` (workflow dependency chain — see AGENTS.md)
- [ ] `infra/config.yaml` (deployment settings)
