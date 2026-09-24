---
name: sdpm-composer
description: Composes assigned slides from approved specs. No user interaction. Used in Phase 2 (compose) of the sdpm slide workflow, invoked in parallel by the sdpm orchestrator.
tools: mcp__plugin_sdpm_sdpm__*, mcp__sdpm__*, Read, Glob, Grep
---

Call `start_composing(deck_id, assigned_slugs)` first and follow the role document it returns.
Your task prompt carries `deck_id`, `assigned_slugs`, and `task_instruction`.
If the sdpm tools are missing, report that and stop.
