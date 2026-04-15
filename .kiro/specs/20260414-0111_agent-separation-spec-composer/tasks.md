# Tasks: エージェント分離と並列スライド生成

## Phase C: 直列エージェント + ファイル分割

### ファイル分割
- [x] Layer 1: _resolve_config のディレクトリ入力対応（deck.json + slides/*.json読み込み）
- [x] Storage ABC に抽象メソッド追加（get/put_deck_json, get/put_slide_json）（storage/__init__.py）
- [x] Storage層に deck.json 読み書きメソッド追加（storage/aws.py）
- [x] Storage層に slides/{slug}.json 読み書きメソッド追加（storage/aws.py）
- [x] outline.md パーサー実装（slug順序リスト取得）
- [x] generate.py: _prepare_workspace と _assemble_slides の分離（I/O とデータ変換を分ける）
- [x] generate.py: _assemble_slides は新形式のみ（deck.json前提、presentation.json後方互換を削除）
- [x] sandbox.py: _WORKSPACE_PREFIXES を更新（deck.json, slides/, specs/, includes/）
- [x] sandbox.py: save を prefix ベース走査方式に変更（paths リスト方式を廃止）
- [x] init.py を deck.json + specs/ 初期化に変更（slides/ は Phase 2 で作成）
- [x] server.py: measure_slides を list[int] → list[str]（slug）に変更
- [x] server.py: lint の presentation.json 直接読みを _assemble_slides 戻り値に変更

### outline.md slug化
- [x] outline ワークフロー（create-new-1-outline.md）をslug形式に変更
- [x] art-direction ワークフロー（create-new-1-art-direction.md）をdeck.json書き込み手順に変更
- [x] WebUI outlineParser.ts のslug形式対応（OutlineSlide: num/title削除、slug追加）
- [x] WebUI OutlineView.tsx の表示調整（ノード円に index+1、slug を太字、message を下に）

### エージェント分離
- [x] SPECエージェントの system prompt 作成
- [x] compose_slides の `@tool` 定義と system prompt 作成（Phase C: 直列実行）
- [x] compose_slides の戻り値レポート実装（generated_slides, outline_check, preview_images, measure_summary, errors）
- [x] briefing ワークフロー強化（制約・個別要望・素材一覧セクション追加）
- [x] SPECエージェント → compose_slides 呼び出しの統合テスト

### Phase C 検証
- [x] ファイル分割でgenerate_pptxが正常動作することを確認
- [ ] sandbox内でdeck.json + slides/{slug}.json の直接編集が動作することを確認
- [ ] sandbox の prefix ベース走査で新規作成ファイルが S3 に保存されることを確認
- [x] ~~Layer 1のpresentation.json後方互換が動作することを確認~~ → 後方互換を削除したため不要
- [x] ~~既存デッキ（presentation.json形式）が _assemble_slides で正常に読めることを確認~~ → 後方互換を削除したため不要
- [x] measure_slides の slug 指定で計測結果が slug ベースで返ることを確認
- [ ] 3ファイルインターフェースだけで十分な品質のスライドが作れるか検証
- [ ] compose_slides の戻り値レポートでSPECエージェントが適切に判断できるか検証
- [ ] SPECエージェント経由の修正指示が機能するか検証
- [x] steering/principles.md を4層構造に更新

### svg-compose-animation-fixes マージ
- [x] feat/svg-compose-animation-fixes をマージ（compose/animation機能の取り込み）
- [x] api/index.py: 旧フォーマット（presentation.json）分岐を削除、新フォーマットのみに
- [x] mcp-server/tools/generate.py: _assemble_slides / _prepare_workspace から旧フォーマットフォールバックを削除
- [x] API Lambda（api/index.py）を新形式（deck.json + slides/*.json）に対応
- [x] compose_slides 進捗表示（tool_stream_event パイプライン）
  - [x] compose_slides を async generator 化 + callback_handler で進捗 yield
  - [x] agent_stream で tool_stream_event を透過的に流す
  - [x] strandsParser.js で tool_stream_event をパース
  - [x] ToolCard.tsx で進捗テキスト表示
  - [x] ChatMessage.tsx の isActive 条件修正（input非空ツールでも active 表示）
- [x] generate.py の outline parser 重複解消（Engine の parse_outline_slugs を使用）
- [x] compose_slides の stream_async ネスト問題修正（invoke_async + callback + Queue パターンへ移行）
- [x] composer コンテキスト事前注入（prefetch最適化）
  - [x] composer system prompt から mcp_instructions を除去
  - [x] _prefetch_context(): MCPClient.call_tool_sync で共通リファレンス5件を取得
  - [x] _prefetch_context(): run_python(deck_id) で specs 4ファイルを取得
  - [x] compose_slides に deck_id 引数を追加
  - [ ] prefetch 結果を system prompt に注入して composer が即行動できることを検証
- [x] Engine measure() を slug 対応に拡張（list[str] 受付、format_measure_report に page_to_slug）
- [x] Layer 3 _run_measure に page_to_slug を渡して slug ベース出力

### 並列化
- [x] compose_slides 内部を asyncio.Semaphore + asyncio.gather による並列実行に切り替え（max_concurrency設定）
- [x] SPECエージェントのsystem promptにグループ分割判断基準を追加（核グループ形成 + 独立スライド負荷均等振り分け）
- [x] 全composer完了後の全体ビルド + レポート組み立てフロー
- [x] Phase 3レビューワークフロー強化（レイアウト重複検出、メッセージ接続、伏線回収、デザイン一貫性）
- [x] WebUI ToolCard のグループ別進捗表示（並列グループを独立ブロックで表示）

### Phase B 検証
- [ ] 並列エージェントが別々のslides/{slug}.jsonに書き込み、競合しないことを確認
- [ ] 並列中の measure で欠損スライドが黙ってスキップされることを確認
- [ ] 速度改善の計測（直列 vs 並列、目標: 10分 → 1-2分）
- [ ] 全スライドの品質均一性を確認（後半品質低下がないこと）
- [ ] コンテキストサイズが1エージェント構成より削減されていることを確認（トークン数計測）

### compose 並列安全化
- [x] compose キーを slug ベースに変更（`slide_{N}_{epoch}.json` → `{slug}_{epoch}.json`）
- [x] compose 生成を measure_slides の slug に限定（全スライド再生成を廃止）
- [x] 旧 compose 削除を担当 slug のキーだけに限定
- [x] epoch を `_prepare_workspace` 開始時点に変更（最新 slides スナップショットの後勝ち）
- [x] sourceHash / prev_by_hash / prev_by_slot / prev_slot_map を削除（slug ベースで直接引くため不要）
- [x] changed 判定を同一 slug の前回 compose との component-level diff に簡素化
- [x] API Lambda の compose キーマッチングを slug ベースに変更
- [x] 未使用 import (count_slides) を削除
- [x] 並列 composer で compose が競合せず両方アニメーションされることを確認
- [x] defs の後勝ちで描画が壊れないことを確認

---
**Created**: 2026-04-14
