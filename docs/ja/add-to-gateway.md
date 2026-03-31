[EN](../en/add-to-gateway.md) | [JA](../ja/add-to-gateway.md)

# エージェント接続ガイド

spec-driven-presentation-maker は MCP サーバーです — Model Context Protocol をサポートする任意の AI エージェントに接続できます。
このガイドでは 3 つの接続オプションを説明します。

---

## オプション 1: ローカル MCP サーバー（Layer 2）

AWS 不要。サーバーはローカルで stdio 経由で動作します。

セットアップ手順と MCP クライアント設定は[はじめに — Layer 2](getting-started.md#layer-2-ローカル-mcp-サーバー)を参照してください。

Kiro Skill として使う場合は、`skill/` を Kiro のスキルディレクトリにコピーするだけです。SKILL.md がワークフロー手順を直接提供します。

---

## オプション 2: Amazon Bedrock AgentCore Gateway（Layer 3、チーム利用推奨）

マルチユーザー環境では、Amazon Bedrock AgentCore Gateway 経由で接続します。Gateway は OAuth ベースの認証、ツール集約、Cedar ベースの認可を提供します。

### 前提条件

- Layer 3 が CDK でデプロイ済み（[はじめに — Layer 3](getting-started.md#layer-3-リモート-mcp-サーバーaws)参照）
- Amazon Bedrock AgentCore Gateway が AWS アカウントに設定済み

### Gateway ターゲットとして登録

spec-driven-presentation-maker Runtime を Amazon Bedrock AgentCore Gateway の MCP Server ターゲットとして追加します。

1. CDK 出力から Runtime ARN を取得（`SdpmRuntime.RuntimeArn`）
2. Gateway からこの Runtime へのルーティングを設定
3. Gateway → Runtime 接続用の OAuth 認証情報を設定（CDK 出力の M2M クライアント情報）

Gateway に接続する MCP クライアントは、spec-driven-presentation-maker のツールを他の登録済み MCP サーバーと共に自動的に検出します。

### 認証フロー

```
MCP Client → Gateway (OAuth) → Runtime (JWT Bearer) → MCP Server コンテナ
```

Gateway がクライアント認証を処理します。Runtime は JWT を検証し、ユーザー ID（`sub` クレーム）を抽出してデッキ単位の認可に使用します。

---

## オプション 3: Runtime 直接アクセス（Layer 3）

Gateway を使わず、Amazon Bedrock AgentCore Runtime エンドポイントに直接接続します。テストやシングルサーバー構成に適しています。

### エンドポイント

```
POST https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT
```

`ENCODED_ARN` は URL エンコードされた Runtime ARN です。

### ヘッダー

```
Content-Type: application/json
Accept: application/json, text/event-stream
Authorization: Bearer {JWT_TOKEN}
```

JWT トークンの取得方法は[はじめに — OAuth トークンの取得](getting-started.md#oauth-トークンの取得)を参照してください。

### 例: ツールの呼び出し

```bash
curl -X POST \
  "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/${ENCODED_ARN}/invocations?qualifier=DEFAULT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_templates",
      "arguments": {}
    },
    "id": 2
  }'
```

---

## 認証設定

認証・認可モデルの設計詳細は[アーキテクチャ — 認証・認可モデル](architecture.md#認証認可モデル)を、Amazon Cognito / 外部 IdP の設定手順は[はじめに — 認証オプション](getting-started.md#認証オプション)を参照してください。

### ユーザー識別

JWT の `sub` クレームがスタック全体でユーザー ID として使用されます。

- デッキの所有権とアクセス制御
- ユーザーごとのデッキ分離
- 監査証跡

追加のユーザー登録は不要です — 有効な JWT に `sub` クレームがあれば動作します。

---

## requestHeaderAllowlist の重要性

Amazon Bedrock AgentCore Runtime はデフォルトで `Authorization` ヘッダーをコンテナに転送しません。spec-driven-presentation-maker はこのヘッダーから JWT の `sub` クレームを抽出して `user_id` として使用するため、転送設定が必須です。

CDK では `RuntimeStack` が自動的に設定しています:

```typescript
requestHeaderConfiguration: {
  requestHeaderAllowlist: ["Authorization"],
},
```

手動で Runtime を作成する場合は、この設定を忘れないでください。設定が漏れると:

- MCP Server がユーザーを識別できない（`user_id` が空になる）
- デッキの作成・読み取りが認可エラーになる
- `403 Forbidden` ではなく `500 Internal Server Error` として表面化する場合がある

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `401 Unauthorized` | JWT トークンが無効または期限切れ | トークンを再取得。`oidcDiscoveryUrl` と `allowedClients` が正しいか確認 |
| `403 Forbidden` | クライアント ID が `allowedClients` に含まれていない | `config.yaml` の `auth.allowedClients` にクライアント ID を追加して再デプロイ |
| `500 Internal Server Error` | `requestHeaderAllowlist` 未設定 | CDK で `requestHeaderAllowlist: ["Authorization"]` を設定して再デプロイ |
| ツール呼び出しでデッキが見つからない | `user_id` の不一致 | 同じ JWT（同じ `sub`）でデッキを作成・参照しているか確認 |
| SSE レスポンスが空 | `Accept` ヘッダー不足 | `Accept: application/json, text/event-stream` を指定 |

---

## 関連ドキュメント

- [はじめに](getting-started.md) — セットアップとデプロイ手順
- [アーキテクチャ](architecture.md) — 認証・認可モデルの詳細
