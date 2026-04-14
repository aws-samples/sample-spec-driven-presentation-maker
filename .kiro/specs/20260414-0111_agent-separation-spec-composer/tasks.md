# Tasks: エージェント分離と並列スライド生成

## Phase C: 直列エージェント + ファイル分割

### ファイル分割
- [x] Layer 1: _resolve_config のディレクトリ入力対応（deck.json + slides/*.json読み込み、presentation.json後方互換）
- [x] Storage ABC に抽象メソッド追加（get/put_deck_json, get/put_slide_json）（storage/__init__.py）
- [x] Storage層に deck.json 読み書きメソッド追加（storage/aws.py）
- [x] Storage層に slides/{slug}.json 読み書きメソッド追加（storage/aws.py）
- [x] outline.md パーサー実装（slug順序リスト取得）
- [x] generate.py: _prepare_workspace と _assemble_slides の分離（I/O とデータ変換を分ける）
- [x] generate.py: _assemble_slides に新旧形式の自動判定（deck.json有無）と欠損スライドの黙スキップ
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
- [ ] ファイル分割でgenerate_pptxが正常動作することを確認
- [ ] sandbox内でdeck.json + slides/{slug}.json の直接編集が動作することを確認
- [ ] sandbox の prefix ベース走査で新規作成ファイルが S3 に保存されることを確認
- [ ] Layer 1のpresentation.json後方互換が動作することを確認
- [ ] 既存デッキ（presentation.json形式）が _assemble_slides で正常に読めることを確認
- [ ] measure_slides の slug 指定で計測結果が slug ベースで返ることを確認
- [ ] 3ファイルインターフェースだけで十分な品質のスライドが作れるか検証
- [ ] compose_slides の戻り値レポートでSPECエージェントが適切に判断できるか検証
- [ ] SPECエージェント経由の修正指示が機能するか検証
- [ ] steering/principles.md を4層構造に更新

## Phase B: 並列エージェント

### 並列化
- [ ] compose_slides 内部を asyncio.Semaphore + asyncio.gather による並列実行に切り替え（max_concurrency設定）
- [ ] SPECエージェントのsystem promptにグループ分割判断基準を追加（核グループ形成 + 独立スライド負荷均等振り分け）
- [ ] 全composer完了後の全体ビルド + レポート組み立てフロー
- [ ] Phase 3レビューワークフロー強化（レイアウト重複検出、メッセージ接続、伏線回収、デザイン一貫性）

### Phase B 検証
- [ ] 並列エージェントが別々のslides/{slug}.jsonに書き込み、競合しないことを確認
- [ ] 並列中の measure で欠損スライドが黙ってスキップされることを確認
- [ ] 速度改善の計測（直列 vs 並列、目標: 10分 → 1-2分）
- [ ] 全スライドの品質均一性を確認（後半品質低下がないこと）
- [ ] コンテキストサイズが1エージェント構成より削減されていることを確認（トークン数計測）

---
**Created**: 2026-04-14
