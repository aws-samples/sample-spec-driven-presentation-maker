---
name: sdpm-style
description: >-
  再利用できるスライドのスタイルガイド（HTML デザイントークン）を対話で作るとき。
  「うちのブランドカラーでテンプレートを作りたい」「この見た目を使い回したい」で起動。
  Create a reusable presentation style guide (HTML design tokens) through dialogue.
---

# sdpm-style

Call `start_presentation(mode="style")` on the **sdpm** MCP server **before any other tool**,
then follow the returned instructions for the rest of the conversation.

Do **not** decide colors, typography, or token structure before those instructions are loaded.

If the sdpm MCP server is unavailable, stop and tell the user that the sdpm MCP server is not
reachable, and that they should check their MCP configuration. Do not improvise a style guide:
the behavior definition lives on the server side, not in this file.
