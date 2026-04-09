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

---

## オプション 4: Generative AI Use Cases on AWS (GenU) 連携

> **注意:** [Generative AI Use Cases on AWS (GenU)](https://github.com/aws-samples/generative-ai-use-cases-jp) は活発に開発が行われている別のオープンソースプロジェクトです。以下の手順は 2026 年 4 月時点の GenU v5.x に基づいており、今後のリリースで変更される可能性があります。

[GenU](https://github.com/aws-samples/generative-ai-use-cases-jp) は、チャット・RAG・画像生成など多様な生成 AI ユースケースを AWS 上で提供するオープンソース Web アプリケーションです。GenU の **AgentCore ユースケース**は、Amazon Bedrock AgentCore Runtime コンテナ内で [Strands Agent](https://strandsagents.com/) を実行し、設定ファイルで定義された MCP ツールを呼び出します。このコンテナに spec-driven-presentation-maker をバンドルすることで、GenU のチャット画面から直接プレゼンテーションを生成できます。

### 前提条件

- GenU リポジトリがクローン済みでデプロイ可能な状態（[GenU README](https://github.com/aws-samples/generative-ai-use-cases-jp) 参照）
- ビルドマシンで Docker が利用可能（AgentCore コンテナイメージのビルドに必要）
- GenU で **AgentCore ユースケースが有効化済み** — `packages/cdk/cdk.json` または `parameter.ts` で `createGenericAgentCoreRuntime: true` を設定（[GenU デプロイオプション](https://github.com/aws-samples/generative-ai-use-cases-jp/blob/main/docs/ja/DEPLOY_OPTION.md)参照）
- x86_64 ホスト（Intel/AMD）では、デプロイ前に `docker run --privileged --rm tonistiigi/binfmt --install arm64` を実行（AgentCore は ARM64 コンテナイメージを要求）

### Step 1: sdpm ファイルを GenU AgentCore Runtime ディレクトリにコピー

スキルパッケージとローカル MCP サーバーを GenU の AgentCore Runtime Docker コンテキストにコピーします：

```bash
GENU_RUNTIME_DIR=<path-to-genu>/packages/cdk/lambda-python/generic-agent-core-runtime

# スキルパッケージ（エンジン、テンプレート、リファレンス、スクリプト）をコピー
cp -r <path-to-sdpm>/skill $GENU_RUNTIME_DIR/sdpm-skill

# ローカル MCP サーバーをコピー
cp -r <path-to-sdpm>/mcp-local $GENU_RUNTIME_DIR/sdpm-mcp-local
```

### Step 2: Dockerfile のパッチ

`$GENU_RUNTIME_DIR/Dockerfile` の `EXPOSE` 行の**前**に以下を追加します：

```dockerfile
# --- SDPM: spec-driven-presentation-maker ---
COPY sdpm-skill/ ./sdpm-skill/
COPY sdpm-mcp-local/ ./sdpm-mcp-local/
RUN uv pip install --python /tmp/.venv/bin/python ./sdpm-skill
# アイコンアセットのダウンロード（AWS Architecture Icons + Material Icons）
RUN /tmp/.venv/bin/python sdpm-skill/scripts/download_aws_icons.py \
 && /tmp/.venv/bin/python sdpm-skill/scripts/download_material_icons.py
# server.py がスキルパッケージを解決できるようシンボリックリンクを作成
RUN ln -s /var/task/sdpm-skill /var/task/skill
```

### Step 3: MCP サーバーの登録

`$GENU_RUNTIME_DIR/mcp-configs/generic/mcp.json` の `mcpServers` に以下のエントリを追加します：

```json
"spec-driven-presentation-maker": {
    "command": "python",
    "args": ["sdpm-mcp-local/server.py"],
    "env": {
        "PYTHONPATH": "/var/task/sdpm-skill",
        "SDPM_OUTPUT_DIR": "/tmp/ws"
    }
}
```

`SDPM_OUTPUT_DIR` は生成ファイルの出力先を指定します。GenU の AgentCore Runtime は `/tmp/ws` 配下のファイルのみ S3 にアップロードできるため、この設定が必要です。組み込みの `upload_file_to_s3_and_retrieve_s3_url` ツールがファイルを S3 にアップロードし、ダウンロード URL をユーザーに返します。

### Step 4: デプロイ

通常通り CDK で GenU をデプロイします。sdpm がバンドルされた AgentCore コンテナイメージが再ビルドされます：

```bash
cd <path-to-genu>
npx -w packages/cdk cdk deploy --all
```

### 動作の仕組み

```
ユーザー → GenU Web UI → Strands Agent (AgentCore Runtime)
                           ├── sdpm MCP ツール (stdio)
                           │   ├── init_presentation
                           │   ├── generate_pptx → /tmp/ws/*.pptx
                           │   └── search_assets, analyze_template, ...
                           └── upload_file_to_s3_and_retrieve_s3_url
                               └── S3 URL → ユーザー
```

エージェントは sdpm の `server_instructions` に従ってプレゼンテーションワークフロー（ヒアリング → アウトライン → コンポーズ → レビュー → 生成）を実行し、生成された PPTX を S3 にアップロードしてダウンロード URL を返します。
