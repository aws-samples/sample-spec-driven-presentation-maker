# Requirements: エージェント分離と並列スライド生成

## Background & Context

### User Problems
- WEB版でコスト肥大化（検索ツール呼び出し、大量トークン入力）
- 1エージェントで全フェーズを実行するとコンテキストが膨らみ、後半で品質低下
- Phase 1（仕様策定）の対話コンテキストがPhase 2（実装）に不要に引き継がれる
- 直列スライド生成は1枚1分以上 × 10枚 = 10分以上。WEB版UXとして許容できない

### Related Issues
- presentation.json が単一ファイルのため、並列書き込みで競合する（last-writer-wins）
- デザイン一貫性の構造的担保

## Objectives
- SPECエージェント（Phase 1）と実装エージェント（Phase 2+3）を分離し、コンテキストを最小化する
- スライド単位のファイル分割により並列生成を可能にする（10分 → 1-2分）
- 3ファイルインターフェース（brief.md, outline.md, art-direction.html）でエージェント間の受け渡しを完結させる

## Scope

### In Scope
- エージェント分離アーキテクチャの設計と実装
- presentation.json のスライド単位分割（deck.json + slides/{slug}.json）
- outline.md のslug化（順序管理 + ファイル名統一）
- briefフローの強化（制約・個別要望・素材情報の明文化）
- Strands Agents SDK の Agents as Tools パターンによる実装
- 並列実装エージェントの実装（asyncio.gather）

### Out of Scope
- A2Aプロトコルによるリモートエージェント分離
- AgentCoreへの本番デプロイ
- MCP toolインターフェースの変更（エージェントから見たツールの使い方は変えない）

## Detailed Requirements

### 1. ファイル分割

現在:
```
decks/{deckId}/presentation.json  ← 全スライド + メタデータが1ファイル
```

分割後:
```
decks/{deckId}/deck.json              ← メタデータのみ
decks/{deckId}/slides/{slug}.json     ← スライド1枚分のdict
```

deck.json の内容:
```json
{
  "template": "selected-template.pptx",
  "fonts": {"fullwidth": "メイリオ", "halfwidth": "Calibri"},
  "defaultTextColor": "#FFFFFF"
}
```

- deck.json はPhase 1（art-direction Step 1）で作成し、Phase 2では読み取り専用とする
- slides/{slug}.json は現在の `slides[i]` の中身そのもの
- slugはoutline.mdのラベルと1:1対応
- スライドの `"id"` フィールドにはslugを使用する（override継承との整合）

### 2. outline.md slug化

現在:
```markdown
- [1: Title] Audience knows the topic and speaker
- [2: Current state] Audience sees the problem
```

変更後:
```markdown
- [title] Audience knows the topic and speaker
- [current-state] Audience sees the problem
```

- slugがファイル名（`slides/{slug}.json`）と直接対応
- 行の順序がスライド順序を定義する
- 挿入は1行追加のみ（50スライドの先頭挿入でもファイルリネーム不要）
- slugの一意性はビルド時バリデーションで保証

### 3. ファイル分割を全レイヤーの正式フォーマットとする

deck.json + slides/{slug}.json を全レイヤーで統一的に扱う:
- Layer 1（Engine）: _resolve_config がディレクトリから deck.json + slides/*.json を読む。measure() が slug（list[str]）を受け付け、結果を slug ベースで出力
- Layer 3（MCP Server）: Storage層、generate.py、sandbox.py が分割構造を直接扱う
- API Lambda: deck.json + outline.md + slides/*.json のみ対応（presentation.json フォールバックなし）
- sandbox: sandbox内も deck.json + slides/{slug}.json 構造。エージェントは `open("slides/{slug}.json")` で直接編集
- マージ/分割の変換レイヤーは設けない
- presentation.json の後方互換は提供しない（新フォーマットのみ）

### 4. generate_pptx のビルド処理

ビルド時に以下の手順でEngine互換dictを組み立てる:
1. deck.json を読む（メタデータ）
2. outline.md をパースしてslugの順序リストを取得
3. slides/{slug}.json を順序通りに読んでslidesリストを構築
4. `{"template": ..., "fonts": ..., "defaultTextColor": ..., "slides": [...]}` をEngineに渡す

### 5. エージェント構造

SPECエージェント（Phase 1担当）:
- briefing → outline → art-direction のワークフローを実行
- ユーザーとの対話を一手に担う（UXの一貫性）
- Phase 2は自分で実行しない（system promptで制約）
- 実装エージェントを `@tool` として呼び出す

実装エージェント（Phase 2 + Phase 3担当）:
- compose（スライド生成）+ review（レビュー・修正）を実行
- 起動時にdeck.json + 担当slides + specs/ + リファレンスを自動ロード
- ステートレス（毎回新規起動、コンテキストはファイルに全てある）

### 6. 並列実装エージェント

- outline.mdのスライドリストをグループに分割し、各グループを別エージェントに割り当て
- グループ分割は2ステップ: (1) デザインを揃えたいスライドで核グループを形成、(2) 独立スライドを負荷均等に振り分け
- 隣接スライドのレイアウト多様性はグループ分割では考慮しない（事後レビューで対応）
- 並列度制御はsemaphore（max_concurrency）で行い、グループ分割の判断と分離する
- 各エージェントはdeck.json + 担当slides/{slug}.jsonだけを読み書き
- 書き込み対象が重複しないため競合しない
- asyncio.gatherで並列起動
- 全エージェント完了後にgenerate_pptxを実行

### 7. インターフェース

エージェント間の受け渡しは既存のファイルのみ:
- `specs/brief.md` — 何を・誰に・なぜ・制約・個別要望・素材情報
- `specs/outline.md` — 各スライドのslug + メッセージ（順序定義を兼ねる）
- `specs/art-direction.html` — デザイントークン・ビジュアル方針
- `deck.json` — メタデータ（Phase 1で確定、Phase 2は読み取り専用）

修正指示のみテキストで渡す（例: 「スライド3の図を拡大」）。

### 8. MCP tools

両エージェントにフルセットのMCP toolsを提供する。
ツールの分割は行わない。制約はsystem promptで制御する。
MCP toolインターフェースの変更は行わない（エージェントから見た使い方は同じ）。

### 9. レビューフロー

- 実装エージェントがPhase 3（review）を担当（実装コンテキストを持っているため）
- ユーザーからの修正要望はSPECエージェントが受け取り、実装指示に変換して渡す
- SPECエージェントは「翻訳者」として機能

### 10. briefフロー強化

briefing ワークフローの Step 3「Write brief」に以下を追加:

#### 制約・個別要望セクション
```markdown
## Constraints & Requests
- [MUST NOT] ...（対話中に出た「〜はやらないで」）
- [MUST] ...（「〜を必ず入れて」）
- [PREFER] ...（「できれば〜」）
```

#### 素材一覧セクション
```markdown
## Materials
| File | Description | Target Slide |
|------|-------------|--------------|
| logo.png | Company logo | title |
| chart.csv | Q1 revenue data | revenue-overview |
```

### 11. 対象レイヤー

既存の4層アーキテクチャのLayer 3-4の変更。

```
Layer 1: Skill (Engine)          ← _resolve_config のディレクトリ入力対応 + measure の slug 対応
Layer 2: Local MCP Server        ← 変更なし（将来対応可）
Layer 3: Remote MCP Server       ← Storage層のファイル分割対応、旧フォーマット(presentation.json)フォールバック削除
Layer 4: Agent + Web UI          ← エージェント分離 + outline slug対応
```

### 12. 技術選定

Strands Agents SDK の Agents as Tools パターンを採用。
- 既存のStrands Agent環境をそのまま活用
- 同一プロセス内で動作（HTTP通信不要）
- `@tool`デコレータで関数をラップするだけ
- 親エージェントのコンテキストがサブエージェントに漏れない
- async対応で並列化が容易

### 13. 実装フェーズ

Phase C（中間チェックポイント）:
- 直列1実装エージェント + ファイル分割
- 検証: 3ファイルインターフェースの品質、ファイル分割の動作、ステートレスエージェントの品質

Phase B（ゴール）:
- 並列実装エージェント
- outline.mdからグループ分割 → asyncio.gatherで並列起動
- 検証: 速度改善（10分 → 1-2分）、品質均一性

---
**Created**: 2026-04-14
