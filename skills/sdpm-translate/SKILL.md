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

Call `start_presentation(mode="translate")` on the **sdpm** MCP server **before any other
tool**, then follow the returned instructions for the rest of the conversation.

Do **not** improvise a translation pipeline before those instructions are loaded — the
derived-deck procedure (extract → dictionary → apply → build) is defined there.

If the sdpm MCP server is unavailable, stop and tell the user that the sdpm MCP server is
not reachable, and that they should check their MCP configuration. Do not improvise: the
behavior definition lives on the server side, not in this file.
