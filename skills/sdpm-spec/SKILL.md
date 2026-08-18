---
name: sdpm-spec
description: >-
  スライド / プレゼン資料 / PowerPoint を spec 駆動で、丁寧なヒアリングを通して作るとき。
  要件・論理構造・デザインを対話で固め、各ステップでユーザー承認を取る。既存 PPTX の編集や
  ガイド付きメニューからのスタイル作成もこちら。「相談しながら資料を作りたい」で起動。
  Dialogue-driven deck design — real hearing, structured requirements, approval at each step.
  Also the entry point for editing an existing PPTX.
---

# sdpm-spec

Call `start_presentation(mode="spec")` on the **sdpm** MCP server **before any other tool**,
then follow the returned instructions for the rest of the conversation.

Do **not** decide slide structure, content, design, or layout before those instructions are
loaded — they define the hearing, the approval gates, and how Phase 2 composition is delegated.

If the sdpm MCP server is unavailable, stop and tell the user that the sdpm MCP server is not
reachable, and that they should check their MCP configuration. Do not improvise a deck: the
behavior definition lives on the server side, not in this file.
