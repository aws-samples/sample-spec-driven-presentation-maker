# 2026-05-04: MCP 自動再接続 & レジリエンス改善

## 背景

Agent セッション内で MCP Server のコンテナが終了した場合（アイドルタイムアウト約 15 分、デプロイ等）、MCPClient が保持する接続が無効になり、以降のツール呼び出しが全て失敗し続ける問題があった。

CloudWatch ログによる根本原因分析:
- MCP Server 最終ツール呼び出し: 22:58:23 JST
- MCP Server コンテナ終了: 23:13:51 JST（15 分 28 秒のアイドルタイムアウト）
- Agent は動作を継続したが、全ての MCP ツール呼び出しが `MCPClientInitializationError: the client session is not running` で失敗
- LLM がリトライを繰り返すが、同じ無効な接続を使い続けるため無限に失敗

## 実装内容

### 1. MCP 自動再接続（`agent/mcp_reconnect.py` — 新規）

Spec: `.kiro/specs/mcp-client-auto-reconnect/`

#### アーキテクチャ

Strands SDK の `AfterToolCallEvent` / `BeforeToolCallEvent` フック機構を活用し、Agent レイヤーで接続断を検知・再接続する。Strands SDK 自体は変更しない。

```
Agent → AfterToolCallEvent → MCPReconnectHandler
  → classify_error() → transient? → reconnect()
    → stop old MCPClient
    → factory_fn() で新 MCPClient 生成（指数バックオフ付きリトライ）
    → Agent.tool_registry を更新
    → SSE イベント発行 → WebUI に通知
```

#### エラー分類（`classify_error()`）

3 段階分類で再接続の要否を判定:

| 分類 | 判定基準 | 再接続 |
|---|---|---|
| `transient` | `ConnectionError`, `TimeoutError`, HTTP 502/503/504, `MCPClientInitializationError`, `ToolProviderException`, `RuntimeError("Connection to the MCP server was closed")`, メッセージに "connection"/"timeout"/"client session is not running" 等を含む | する |
| `permanent` | HTTP 401/403, メッセージに "unauthorized"/"forbidden"/"certificate" 等を含む | しない |
| `not_connection` | 上記以外（`ValueError`, `TypeError` 等のツールロジックエラー） | しない |

判定の優先順位:
1. 例外型の直接判定（`isinstance`）
2. Strands SDK 固有エラーの型名判定（`MCPClient*`, `ToolProvider*`）
3. HTTP ステータスコード
4. エラーメッセージのパターンマッチ（フォールバック）

`event.exception`（Strands SDK が `AfterToolCallEvent` に渡す実例外）を優先使用し、利用できない場合のみエラーメッセージから合成例外を作成する。

#### 再接続フロー（`reconnect()`）

1. `_reconnect_lock` で同一サーバーの並行再接続を防止
2. 既存 MCPClient の `stop()` 呼び出し（リソース解放）
3. ファクトリ関数で新しい MCPClient を生成
4. 指数バックオフ付きリトライ（最大 3 回、`min(base_delay * 2^attempt + jitter, max_delay)`）
5. 成功時: Agent の `tool_registry` を更新（旧ツール削除 → 新ツール登録）
6. 各ステップで `ReconnectEvent` を SSE イベントキューに追加

#### 必須/任意サーバーの区別

| サーバー | `required` | 再接続失敗時の動作 |
|---|---|---|
| Presentation Maker | `True` | エラー通知、MCP ツール呼び出しを無効化 |
| AWS Knowledge | `False` | 警告ログ、当該サーバーのツールを無効化、残りで継続 |
| AWS Pricing | `False` | 同上 |

#### Composer Agent 連携

`create_composer_mcp()` で同じ JWT トークンを使用して新しい MCPClient を生成。Composer Agent は各グループ実行時にファクトリ経由で MCPClient を生成するため、`MCPReconnectHandler` を参照するクロージャに変更。

#### スレッドセーフティ

| コンポーネント | 同期メカニズム |
|---|---|
| `reconnect()` | `threading.Lock` + `_reconnecting` dict |
| SSE イベントキュー | `queue.Queue`（スレッドセーフ） |
| Composer Agent | 独立した MCPClient（共有なし） |

### 2. WebUI の再接続通知表示

`McpStatusBar.tsx` に 3 つの新しいステータスを追加:

| ステータス | スタイル | 表示 |
|---|---|---|
| `reconnecting` | 青、🔄 アニメーション | 「MCP Server 'X' への再接続を試みています...」 |
| `reconnected` | 緑、✅ | 「MCP Server 'X' への接続が復旧しました」 |
| `failed` | 赤、❌ | 「MCP Server 'X' への接続を復旧できませんでした」 |

`ChatPanel.tsx` で reconnect イベント（単一オブジェクト）を既存ステータス配列にマージする処理を追加。

### 3. LoopGuard 改善（`agent/resilience.py`）

#### 問題

CloudWatch ログで確認した事実:
- 10:42:36 JST に `fingerprint 5a5075991319 repeated 3x` で LoopGuard が発動し `agent.cancel()` が呼ばれた
- ツール呼び出しは全て成功（HTTP 200 OK）しており、正常なスライド生成フローの一部だった
- `get_preview(deck_id)` のような呼び出しは引数もステータスも毎回同一のため、正常な繰り返しが fingerprint に引っかかる

#### 変更

- **エラー時のみカウント**: `status == "error"` の場合のみ fingerprint をカウント。成功した呼び出しは `max_tool_calls=300` のハードキャップでのみ制限
- `fingerprint_repeat_limit`: 3 → 5 に引き上げ（Composer の `ERROR_LIMIT=5` と整合）

#### 防御の段階

```
1. Composer ERROR_LIMIT (5回連続エラー) → ソフトストップ（LLM に「止めて」と伝える）
2. LoopGuard fingerprint (5回同一エラー) → ハードストップ（agent.cancel()）
3. LoopGuard max_tool_calls (300回) → ハードストップ（最終防衛線）
```

### 4. LLM 応答タイムアウト（`agent/factory.py`）

メイン Agent の `BedrockModel` に `boto_client_config=BotocoreConfig(read_timeout=120)` を追加。Composer の BedrockModel には既に設定済みだったが、メイン Agent だけ未設定だった不整合を修正。

### 5. WebUI デバウンスガード（`web-ui/src/components/chat/ChatPanel.tsx`）

`handleSend` に 500ms デバウンスガードを追加。`lastSendRef` で最終送信時刻を追跡し、500ms 以内の重複送信を拒否。

CloudWatch ログで確認した事実: WebUI が同じセッションに 109ms 差で 2 リクエストを送信し、リクエスト B がリクエスト A をキャンセルした後にハングが発生していた。

### 6. デバッグログ（`agent/streaming.py`）

- `stream_agent started for session X` — ループ開始時
- `stream_agent keepalive #N for session X (in_tool=..., cancel=...)` — keepalive 10 回ごと
- `stream_agent completed for session X (keepalives=N)` — 正常終了時

次回ハングが発生した場合、keepalive ログの有無で Agent プロセスが生きているかを判定可能。

### 7. idleRuntimeSessionTimeout の revert（`infra/lib/agent-stack.ts`, `runtime-stack.ts`）

一度 3600 秒（1 時間）に延長したが、以下の理由で削除しデフォルト（約 15 分）に戻した:
- デプロイ後のコード反映が 1 時間遅れる（既存コンテナが終了するまで新コードが使われない）
- `stop-runtime-session` API は OAuth 認証の Runtime に対して SigV4 から呼べない（`AccessDeniedException: Authorization method mismatch`）ため、強制終了の手段がない
- 自動再接続機能が実装されたため、15 分のアイドルタイムアウト後のコールドスタートは自動再接続で対処可能

### 8. Steering 更新（`.kiro/steering/deploy.md`）

「デプロイ前チェックリスト（必須）」セクションを追加:
1. ローカルテスト（`uv run pytest tests/ -q`）
2. 構文チェック（`ast.parse`）
3. 考慮点の漏れチェック（Dockerfile COPY 行、戻り値の整合性、新規環境変数等）
4. 影響範囲の最小化（`deploy_webui.sh` や `--stack` オプションの活用）
5. デプロイ後の確認（CloudWatch ログチェック）

教訓: 初回デプロイで `agent/Dockerfile` の COPY 行に `mcp_reconnect.py` を追加し忘れ、全コンテナが `ModuleNotFoundError` で起動失敗した。

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `agent/mcp_reconnect.py` | 新規 | MCPReconnectHandler（エラー分類、再接続、SSE 通知） |
| `agent/factory.py` | 変更 | MCPReconnectHandler 統合、read_timeout=120 |
| `agent/basic_agent.py` | 変更 | reconnect_handler を stream_agent に渡す |
| `agent/streaming.py` | 変更 | reconnect イベント注入、デバッグログ |
| `agent/resilience.py` | 変更 | LoopGuard: エラーのみカウント、limit 3→5 |
| `agent/Dockerfile` | 変更 | COPY に mcp_reconnect.py 追加 |
| `web-ui/.../McpStatusBar.tsx` | 変更 | reconnecting/reconnected/failed 表示 |
| `web-ui/.../ChatPanel.tsx` | 変更 | reconnect イベントマージ、500ms デバウンス |
| `infra/lib/agent-stack.ts` | 変更 | mcpCustomScope 追加、idleRuntimeSessionTimeout revert |
| `infra/lib/runtime-stack.ts` | 変更 | idleRuntimeSessionTimeout revert |
| `infra/bin/infra.ts` | 変更 | mcpCustomScope パススルー |
| `infra/lib/web-ui-stack.ts` | 変更 | OAuth scope に MCP スコープ追加 |
| `tests/test_mcp_reconnect.py` | 新規 | 44 テスト（ユニット 37 + プロパティ 7） |
| `docs/changelog/...` | 新規 | 本ドキュメント |
| `.kiro/steering/deploy.md` | 変更 | デプロイ前チェックリスト追加 |
| `pyproject.toml` | 変更 | dev 依存に hypothesis 追加 |

## テスト

- 全テスト: **182 passed, 1 skipped**
- 新規テスト内訳:
  - エラー分類: 15 テスト（ConnectionError, TimeoutError, HTTP codes, MCPClientInitializationError, ToolProviderException, RuntimeError, メッセージパターン）
  - バックオフ: 2 テスト（範囲内、単調増加）
  - ReconnectEvent: 3 テスト（各タイプの to_dict）
  - should_reconnect: 4 テスト（transient/permanent/not_connection/already_reconnecting）
  - reconnect フロー: 6 テスト（成功、全リトライ失敗、イベント発行、旧クライアント停止、並行ブロック）
  - 必須/任意: 2 テスト（required=True/False の失敗イベント）
  - 独立性: 1 テスト（サーバー間の再接続が独立）
  - Composer: 1 テスト（同じ JWT で新 MCPClient 生成）
  - イベントキュー: 3 テスト（empty/drain/has_pending）
  - MCPClientInitializationError E2E: 3 テスト（実例外あり/なし/非接続エラー無視）
  - プロパティテスト（hypothesis）: 7 テスト（各 100-200 イテレーション）

## コミット履歴

| コミット | 内容 |
|---|---|
| `3f3e84c` | feat(agent): MCP 自動再接続 + LoopGuard 改善 + WebUI デバウンス + デバッグログ |
| `3986188` | feat(infra): idleRuntimeSessionTimeout 3600s + MCP custom scope |
| `77258fb` | revert(infra): idleRuntimeSessionTimeout を削除しデフォルト 15 分に戻す |

## 調査で判明した事実（未解決）

### ふんづまり問題

CloudWatch ログと CloudTrail の突き合わせにより判明:

1. WebUI が同じセッションに 109ms 差で 2 リクエストを送信（11:01:54.120 と 11:01:54.229 JST）
2. リクエスト B がリクエスト A をキャンセル（`Signalled previous request cancellation`）
3. リクエスト B の Agent は正常に MCP 接続を確立し、Bedrock への `ConverseStream` も全て正常完了（CloudTrail で確認: 11:08:47〜11:11:11 JST に 8 回の呼び出し、全て outputTokens あり）
4. 11:11:11 JST 以降、Bedrock への呼び出しも Agent ログも途絶える
5. Bedrock 側の問題ではない（CloudTrail で全呼び出し成功を確認済み）
6. Agent プロセス内部でストリーミングループが停止した可能性

対策済み: デバウンスガード（500ms）、read_timeout=120、streaming.py にデバッグログ追加。次回発生時に keepalive ログで原因を特定可能。

### AgentCore Runtime のコンテナ管理

#### 認証方式と API アクセス

AgentCore Runtime は IAM SigV4 と JWT Bearer Token のいずれか一方のみをサポートする（公式ドキュメント: [runtime-oauth.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)）。

> An AgentCore Runtime can support either IAM SigV4 or JWT Bearer Token based inbound auth, but not both simultaneously.

SDPM の Agent Runtime は JWT Bearer Token 認証で構成されているため:

| 操作 | SigV4（AWS CLI / boto3） | OAuth Bearer Token（HTTPS） |
|---|---|---|
| `stop-runtime-session` | ❌ `AccessDeniedException: Authorization method mismatch` | ✅ 動作確認済み |
| `invoke-agent-runtime` | ❌ 同上 | ✅（WebUI が使用） |

#### `stop-runtime-session` の呼び方（検証済み）

公式ドキュメント: [runtime-stop-session.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-stop-session.html)

```python
import urllib.parse, urllib.request

agent_arn = "arn:aws:bedrock-agentcore:us-east-1:867694312594:runtime/sdpm_agent-20nCH0F8Em"
session_id = "<runtimeSessionId>"  # CloudWatch ログの sessionId フィールドから取得
token = "<access_token>"  # ブラウザ開発者ツール > Application > Local Storage から取得

encoded_arn = urllib.parse.quote(agent_arn, safe="")
url = f"https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/{encoded_arn}/stopruntimesession?qualifier=DEFAULT"

req = urllib.request.Request(url, method="POST", data=b"", headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
})
with urllib.request.urlopen(req) as resp:
    print(resp.status, resp.read().decode())
```

検証結果（2026-05-04）:
- セッション `4e2f3c45-4152-4af2-b4a1-7a96f0b6d626` に対して実行 → `404: Session not found or has been terminated`（既にアイドルタイムアウトで終了済み）
- 認証は成功（`AccessDeniedException` ではなく `404` が返った）

#### コンテナの入れ替わり

- デプロイ後、既存コンテナは即座には入れ替わらない
- コンテナが入れ替わるのはアイドルタイムアウト（デフォルト約 15 分）で自然終了した後
- `idleRuntimeSessionTimeout` を 3600 秒に延長するとデプロイ反映が 1 時間遅れるため、デフォルト（15 分）に戻した
- WebUI の「New」ボタンは React コンポーネントの再マウントのみで、Agent コンテナの再起動とは無関係（コード確認済み: `ChatPanelShell.tsx` の `handleNewChat`）
- デプロイ後にすぐ反映したい場合は、上記の `stop-runtime-session` を OAuth Bearer Token で呼ぶ
