---
name: sdpm-translate
description: >-
  既存のスライドデッキ（sdpm デッキ）を別言語に翻訳した派生デッキを作るとき。
  「このデッキを英語にして」「日本語版を作って」「translate this deck」などで起動。
  元デッキは変更せず、隣に言語違いのデッキを生成する。
  Translate an existing sdpm deck into another language as a derived deck.
  The source deck is left untouched.
---

# sdpm-translate

Call `start_translation(deck_id, language)` on the **sdpm** MCP server before any other tool,
then follow it.

If the sdpm MCP server is unavailable, stop and tell the user that it is unavailable.
