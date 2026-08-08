---
name: sdpm-vibe
description: >-
  手元の素材（URL・論文・議事録・PDF・貼り付けテキスト）から、ヒアリング最小・確認なしで
  スライド / プレゼン資料 / PowerPoint を一気に高速生成するとき。
  「これをスライドにして」「このURLから資料作って」「ざっとパワポに」などで起動。
  Fast, autonomous slide/deck/PowerPoint generation from source material the user already
  has. Minimal questions, no per-step approval.
---

# sdpm-vibe

Call `start_presentation(mode="vibe")` on the **sdpm** MCP server **before any other tool**,
then follow the returned instructions for the rest of the conversation.

Do **not** decide slide structure, content, design, or layout before those instructions are
loaded — they define the whole workflow, including how Phase 2 composition is delegated.

If the sdpm MCP server is unavailable, stop and tell the user that the sdpm MCP server is not
reachable, and that they should check their MCP configuration. Do not improvise a deck: the
behavior definition lives on the server side, not in this file.
