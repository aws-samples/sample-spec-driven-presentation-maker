---
name: sdpm-composer
description: >-
  オーケストレーターのサブエージェントとして、割り当てられたスライドを構成・生成するとき。
  Composes assigned slides; used by the presentation orchestrator's sub-agents.
---

# sdpm-composer

Call `read_workflows(["composer"])` on the **sdpm** MCP server before any other tool,
then follow it. Your task prompt carries `deck_id`, `assigned_slugs`, and `task_instruction`.

If the sdpm MCP server is unavailable, stop and report that it is unavailable.
