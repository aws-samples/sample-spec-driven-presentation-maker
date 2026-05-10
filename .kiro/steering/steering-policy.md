<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Steering Policy

## Overview
`.kiro/steering/` contains project principles and rules.
Referenced by both AI agents and human contributors.

## Git Management
- All steering files are excluded by `.gitignore` by default (safe by default)
- Public files are opt-in via `!.kiro/steering/<filename>` in `.gitignore`
- Public files must include `<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->` at the top

## SPEC Files
- `.kiro/specs/` is excluded from git via `.gitignore`
- **Never `git add -f` or force-commit SPEC files** — SPECs are local-only assets
