# Notes: SPECエージェントと実装エージェントの分離

Guidelines:
- **Purpose**: Record sufficient information so that:
  - Future sessions can understand the full context
  - Knowledge notes and learning materials can be generated from this log
  - Issues can be traced and verified through the timeline
- **What to capture**:
  - **Facts**: What happened, what was tried, results and errors
  - **Decisions**: Why this approach, what alternatives were considered
  - **Impressions**: Concerns, surprises, discoveries, evaluations
- **When to record**: After each meaningful unit of work (e.g., investigation, decision, problem resolution). Do not defer.
- **Append-only**: Never edit or delete existing content

## Log

### [2026-04-15 09:41] measure の slug 対応 — Engine まで一貫化

#### 問題
`format_measure_report` が `Slide {page_num}:` でページ番号を出力していた。
Layer 3 の `run_python` は slug → ページ番号変換を持っていたが、結果の逆変換がなかった。
さらに Engine の `measure()` API 自体が `list[int]` しか受け付けず、slug の概念がなかった。

#### 検討
Layer 3 で文字列置換する案もあったが、Engine がディレクトリ入力（deck.json + slides/*.json）に
対応した時点で measure も slug ベースにするのが自然。Layer 3 だけの対処は不整合を放置することになり、
Layer 2 が将来 slug 対応する際にまた同じ変換を書くことになる。
requirements.md の「Layer 1: 軽微な変更」というスコープ記述が実態に追いついていなかった。

#### 修正内容（commit: 61c8006）
- `skill/sdpm/preview/measure.py`: `format_measure_report` に `page_to_slug` オプション追加
- `skill/sdpm/api.py`: `measure()` が `list[str]`（slug）を受け付けるように拡張
- `mcp-server/server.py`: `_run_measure` に `page_to_slug` を渡す

Layer 2 は `list[int]` のまま呼んでも `page_to_slug=None` で従来通り動くので後方互換維持。

### [2026-04-15 09:42] 並列化実装 — 4タスク完了

#### 1. compose_slides 並列化（commit: c857d82）
直列 `for` ループを `asyncio.Semaphore` + `asyncio.gather` に切り替え。
- 全グループ共有の `asyncio.Queue` で進捗を集約
- `return_exceptions=True` で個別失敗を収集、失敗グループのみ直列リトライ（最大1回）
- `COMPOSER_MAX_CONCURRENCY` 環境変数（デフォルト 3）

注意点: `_prefetch_deck_specs` が `call_tool_sync`（同期呼び出し）を使っており、並列時に event loop をブロックする可能性がある。実測で確認が必要。

#### 2. グループ分割判断基準（commit: 011a50d）
SPEC エージェントの system prompt に 2 ステップのグループ分割基準を追加。

#### 3. 全体ビルド + レポート組み立て（commit: 011a50d）
compose_slides の最後に generate_pptx + outline_check を実行。
preview_images はレポートに含めない（SPEC エージェントが事後レビューで get_preview を自分で呼ぶ）。

#### 4. 事後レビューワークフロー（commit: 9a8b8f3）
SPEC エージェントの system prompt に事後レビュー手順を追加。

### [2026-04-15 10:37] WebUI グループ別進捗表示（commit: 46d3ece）

並列 composer の進捗が ToolCard 内で混ざって表示されていた問題を修正。
streamMessages を group 番号でグルーピングし、各グループを独立した角丸ブロックとして表示。
完了グループはチェックマーク、アクティブグループはスピナー + サブツールフィード。

---
**Created**: 2026-04-14

### [2026-04-15 10:56] svg-compose-animation-fixes マージ + 旧フォーマット一掃

#### 背景
feat/svg-compose-animation-fixes が近々 main にマージ予定。agent-separation ブランチに先に取り込んで
compose/animation 機能を使えるようにしたかった。

#### マージ
26コミット差分。コンフリクトは2ファイル3箇所:
- `api/index.py`: deck.json検出ロジック vs compose keys収集ロジック
- `mcp-server/server.py`: `_export_svg` 分離 vs `_run_measure` の `page_to_slug` 引数追加
- `mcp-server/server.py`: measure/lint/bias呼び出しのインターフェース差異

解消方針: HEAD側の slug→page 変換ロジックを維持しつつ、svg側の `_export_svg` 分離と compose 機能を統合。

#### 旧フォーマット削除の判断
マージ後、compose対応の整合性を検証する中で「新フォーマット前提で進めるのに旧フォーマットの分岐を残す必要があるか」
という問いが出た。agent-separation は新フォーマット（deck.json + slides/*.json）前提のアーキテクチャなので、
旧フォーマットの互換コードは不要な複雑さでしかない。

削除対象:
- `api/index.py`: `has_deck_json` 分岐と legacy else ブロック（presentation.json 読み取り）
- `mcp-server/tools/generate.py`: `_assemble_slides` の presentation.json フォールバック、`_prepare_workspace` の新旧判定

結果: 2ファイルから -50行。`has_deck_json` がソースコードから完全に消えた。

#### 残存する presentation.json 参照
- `mcp-server/server.py` の `convert_pptx` ツール: PPTX→JSON変換の出力先として presentation.json を使用。
  これは「旧フォーマットの読み取り」ではなく「変換出力」なので別の話。新フォーマットへの変換出力に変えるかは別途判断。
- `skill/sdpm/api.py`: Engine の `init_presentation` が presentation.json を出力。Layer 1 の変更は別スコープ。
- docstring内の参照: 実害なし、順次更新。

#### 学び
マージで他ブランチの変更を取り込む際、「そのまま統合」ではなく「前提の変化に合わせて不要コードを削る」判断が重要。
旧フォーマット対応を残したままだと、今後の変更で常に2パスのテストが必要になり、開発速度が落ちる。
