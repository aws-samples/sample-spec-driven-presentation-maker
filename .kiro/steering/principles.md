# Principles

## Architecture: 3-Layer Structure

```
Layer 1: CLI (skill/scripts/pptx_builder.py)
  ↓ uses
Skill Engine (skill/sdpm/)          ← Core business logic
  ↑ uses                ↑ uses
Layer 2: MCP Local      Layer 3: MCP Remote
(mcp-local/)            (mcp-server/)
```

## Engine (`skill/sdpm/`)

PPTX生成エンジン。ビジネスロジックの唯一の実装場所。

- `sdpm.builder` — PPTX構築（スライド生成、テンプレート処理）
- `sdpm.preview` — プレビュー（PDF/PNG変換、autofit、レイアウト検証）
- `sdpm.reference` — リファレンスドキュメントアクセス
- `sdpm.api` — 高レベルAPI（generate, preview, init, code_block）
- `sdpm.analyzer`, `sdpm.converter`, `sdpm.layout`, `sdpm.utils` — 各種ユーティリティ

## Skill (`skill/`)

Engine + CLI + リファレンスドキュメント + テンプレートを含むパッケージ。
`sdpm-skill` としてインストールされ、Layer 2/3 から依存される。

## MCP Local (`mcp-local/`) — Layer 2

ローカル環境で動作するMCPサーバー。**薄いラッパー**であること。

- 入力: MCPプロトコルのJSON params → Engine APIの引数に変換
- 処理: Engine API (`sdpm.api.*`, `sdpm.reference.*`) を呼ぶ
- 出力: 結果をJSON文字列に変換して返す
- 独自ロジックを持たない（Engine APIに存在しないロジックを書かない）

## MCP Remote (`mcp-server/`) — Layer 3

AWS上で動作するMCPサーバー。S3/DynamoDB依存がある。

- S3 Storage経由のファイルアクセスなど、インフラ依存の処理は独自実装が許容される
- ただし、Engine内に同等のロジックがある場合はそちらを使う

## ロジック共通化の原則

### CLIが正本
CLIの現行動作が仕様の源泉。Engine APIはCLIの挙動を正確に再現する。

### 共通化の判断基準

共通化する:
- データ取得・変換のロジック（ファイル走査、frontmatter strip、pptxノート取得など）
- ビジネスルール（テンプレート解決、icon検証、autofit、imbalance check）
- 計算ロジック（grid計算、コードハイライト、レイアウト）

共通化しない:
- I/O形式の違い（CLI: print/stdin、MCP Local: JSON、MCP Remote: S3/DynamoDB）
- 環境固有の処理（MCP RemoteのS3 Storage、CLIのargparse）
- UI層の処理（エラーメッセージのフォーマット、ブラウザ起動の有無）

### 迷ったときの判断フロー
1. そのロジックはCLIにあるか？ → あればEngine APIに切り出して共通化
2. インフラ依存か？ → S3/DynamoDB等に依存するならMCP Remote独自実装を許容
3. 表示・出力の違いだけか？ → Engine APIでデータを返し、各層で出力を制御
