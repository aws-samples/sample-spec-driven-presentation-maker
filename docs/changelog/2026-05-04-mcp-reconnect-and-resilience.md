# 2026-05-04: MCP 自動再接続 & レジリエンス改善

## 概要

MCP Server コンテナ終了後に MCPClient の接続が無効になり、以降のツール呼び出しが全て失敗し続ける問題を解決する自動再接続機能を実装した。加えて、調査中に発見した LoopGuard の誤検知問題と LLM 応答ハングの対策も実施した。

## 変更一覧

### 1. MCP 自動再接続（Spec: `.kiro/specs/mcp-client-auto-reconnect/`）

**新規ファイル: `agent/mcp_reconnect.py`**

- `MCPReconnectHandler`: AfterToolCallEvent フックで接続エラーを検知し、指数バックオフ付きリトライで MCPClient を再初期化
- `classify_error()`: エラーを transient / permanent / not_connection に 3 段階分類
  - 例外型（ConnectionError, TimeoutError 等）
  - HTTP ステータスコード（502/503/504 → transient、401/403 → permanent）
  - Strands SDK 固有エラー（MCPClientInitializationError, ToolProviderException, RuntimeError "Connection to the MCP server was closed"）
  - エラーメッセージのパターンマッチ（フォールバック）
- `reconnect()`: 旧 MCPClient の stop → 新 MCPClient 生成 → Agent の tool_registry 更新
- `before_tool_hook()`: 再接続中のツール呼び出しをブロック（60 秒タイムアウト）
- `after_tool_hook()`: `event.exception`（Strands SDK が渡す実例外）を優先使用
- SSE イベント発行: reconnecting / reconnected / failed を WebUI にリアルタイム通知
- Composer Agent 連携: `create_composer_mcp()` で同じ JWT トークンを使用

**変更ファイル: `agent/factory.py`**

- `MCPReconnectHandler` の生成とフック登録（LoopGuard の前に登録）
- `create_agent()` の戻り値に `reconnect_handler` を追加
- Composer MCP ファクトリを `reconnect_handler.create_composer_mcp` 経由に変更
- メイン Agent の BedrockModel に `read_timeout=120` を追加（Composer と統一）

**変更ファイル: `agent/basic_agent.py`**

- `create_agent()` の戻り値から `reconnect_handler` を受け取り `stream_agent` に渡す

**変更ファイル: `agent/streaming.py`**

- `stream_agent()` に `reconnect_handler` パラメータ追加
- イベント処理後と keepalive 時に `drain_events()` で再接続イベントを SSE ストリームに注入
- デバッグログ追加: ループ開始、keepalive カウント（10 回ごと）、正常終了

**変更ファイル: `agent/Dockerfile`**

- COPY 行に `mcp_reconnect.py` を追加（初回デプロイで漏れて `ModuleNotFoundError` が発生）

### 2. WebUI の再接続通知表示

**変更ファイル: `web-ui/src/components/chat/McpStatusBar.tsx`**

- `McpServerStatus` インターフェースに `reconnecting` / `reconnected` / `failed` ステータスを追加
- reconnecting: 青（🔄 アニメーション）、reconnected: 緑（✅）、failed: 赤（❌）

**変更ファイル: `web-ui/src/components/chat/ChatPanel.tsx`**

- reconnect イベント（単一オブジェクト）を既存ステータス配列にマージする処理を追加
- `handleSend` に 500ms デバウンスガード追加（重複送信防止）

### 3. LoopGuard 改善

**変更ファイル: `agent/resilience.py`**

- `fingerprint_repeat_limit`: 3 → 5 に引き上げ
- **エラー時のみカウント**: `status == "error"` の場合のみ fingerprint をカウントするように変更。成功した呼び出しの繰り返し（プレビュー取得等）で誤検知しなくなった

**変更理由（CloudWatch ログで確認）**:
- 10:42:36 JST に `fingerprint 5a5075991319 repeated 3x` で LoopGuard が発動
- ツール呼び出しは全て成功（HTTP 200 OK）しており、正常なスライド生成フローの一部だった
- 成功した呼び出しをカウントする設計が誤検知の原因

### 4. Steering 更新

**変更ファイル: `.kiro/steering/deploy.md`**

- 「デプロイ前チェックリスト（必須）」セクションを追加
  - ローカルテスト必須
  - 構文チェック
  - 考慮点の漏れチェック（Dockerfile COPY 行、戻り値の整合性等）
  - 影響範囲の最小化
  - デプロイ後の確認

## テスト

- 新規テスト: `tests/test_mcp_reconnect.py`（44 テスト）
  - ユニットテスト: 37 テスト（エラー分類、バックオフ、再接続フロー、必須/任意区別、独立性、Composer、イベントキュー、MCPClientInitializationError エンドツーエンド）
  - プロパティテスト: 7 テスト（hypothesis、各 100-200 イテレーション）
- 全テスト: **182 passed, 1 skipped**
- dev 依存に `hypothesis>=6.152.4` を追加

## 調査で判明した事実（未解決）

### ふんづまり問題

CloudWatch ログと CloudTrail の突き合わせにより、以下が判明：

1. **WebUI が同じセッションに 109ms 差で 2 リクエストを送信**（11:01:54.120 と 11:01:54.229 JST）
2. リクエスト B がリクエスト A をキャンセル（`Signalled previous request cancellation`）
3. リクエスト B の Agent は正常に MCP 接続を確立し、Bedrock への `ConverseStream` も全て正常完了（CloudTrail で確認: 11:08:47〜11:11:11 JST に 8 回の呼び出し、全て成功）
4. **11:11:11 JST 以降、Bedrock への呼び出しも Agent ログも途絶える**
5. Bedrock 側の問題ではない（CloudTrail で全呼び出し成功を確認済み）
6. Agent プロセス内部でストリーミングループが停止した可能性

**対策済み**: デバウンスガード（500ms）、`read_timeout=120`、streaming.py にデバッグログ追加。次回発生時に keepalive ログで原因を特定可能。
