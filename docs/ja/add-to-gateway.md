[EN](../en/add-to-gateway.md) | [JA](../ja/add-to-gateway.md)

# エージェント接続ガイド

spec-driven-presentation-maker は MCP サーバーです — Model Context Protocol をサポートする任意の AI エージェントに接続できます。
このガイドでは接続オプションを説明します。

---

## オプション 1: ローカル MCP サーバー（Layer 2）

AWS 不要。サーバーはローカルで stdio 経由で動作します。

セットアップ手順と MCP クライアント設定は[はじめに — Layer 2](getting-started.md#layer-2-ローカル-mcp-サーバー)を参照してください。

---

## オプション 2: OAuth 2.1 Discovery エンドポイント経由（Layer 3、推奨）

Layer 3 のデプロイが必要です（[はじめに — Layer 3](getting-started.md#layer-3-リモート-mcp-サーバーaws)参照）。

CDK デプロイ時に作成される **MCP Server URL**（API Gateway HTTP API）を MCP クライアントに登録するだけで、OAuth 2.1 Discovery プロトコルにより認証が自動的に行われます。

### 接続方法 A: Dynamic Client Registration（DCR）— デフォルト

主要な MCP クライアント（Claude.ai、Claude Desktop、Cursor、VS Code、Kiro）はすべて DCR（RFC 7591）に対応しています。MCP クライアントに MCP Server URL を登録するだけで、クライアントが自動的に OAuth ディスカバリー → DCR → 認証コードフロー を実行します。

#### MCP クライアント設定

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "url": "<McpServerUrl>"
    }
  }
}
```

`<McpServerUrl>` は CDK 出力の `SdpmRuntime.McpServerUrl` から取得してください。

### 接続方法 B: 静的クライアント登録（`auth.mcpCallbackUrls`）

以下のいずれかに該当する場合は、DCR の代わりに静的な OAuth クライアントを使用します：

- **MCP クライアントが DCR に対応していない場合**
- **DCR を許可せず、特定のクライアントのみ接続を許可したい場合**（企業環境でのセキュリティ要件）

> **注意**: DCR を無効化すると、`localhost` で毎回異なるポートの callback URL を使用するクライアントは接続できません。

#### 設定手順

1. `config.yaml` に許可するクライアントの callback URL を記載し、必要に応じて DCR を無効化します：

```yaml
auth:
  enableDCR: false  # DCR を無効化（特定クライアントのみ許可する場合）
  mcpCallbackUrls:
    - https://claude.ai/api/mcp/auth_callback
    - https://claude.com/api/mcp/auth_callback
```

2. 再デプロイします（`cdk deploy --all`）
3. CDK 出力の `SdpmRuntime.McpOAuthClientId` を MCP クライアントに設定します

> **注意**: `enableDCR: false` に設定すると、`/.well-known/oauth-authorization-server` メタデータから `registration_endpoint` が省略され、`/register` は 403 を返します。`mcpCallbackUrls` に登録されていないクライアントは接続できません。

#### デプロイパターン一覧

| `mcpCallbackUrls` | `enableDCR` | 動作 |
|---|---|---|
| なし | `true`（デフォルト） | DCR のみ。個人・デモ向け |
| あり | `true` | 静的クライアント＋DCR 併用 |
| あり | `false` | 静的クライアントのみ。企業向けロックダウン |
| なし | `false` | 外部 MCP 接続なし。WebUI 専用 |

---

## セキュリティ: MCP エンドポイントの保護

Runtime エンドポイントは **Public インターネットに公開** されます。認証（Cognito JWT / IAM）により不正アクセスは防止されますが、次の追加対策を **強く推奨** します。

### WAF による IP 制限

`config.yaml` の `waf.allowedIpV4AddressRanges` / `allowedIpV6AddressRanges` を設定することで、CloudFront と API Gateway に AWS WAF のルールを適用できます。社内 VPN や特定オフィスからのみアクセスさせる場合に有効です。

```yaml
waf:
  allowedIpV4AddressRanges:
    - "192.0.2.0/24"      # 社内ネットワーク IPv4
    - "203.0.113.10/32"   # 個別 IP
  allowedIpV6AddressRanges:
    - "2001:db8::/32"     # 社内ネットワーク IPv6
```

**重要**: Runtime エンドポイント（`bedrock-agentcore.*.amazonaws.com`）自体は AWS サービスが管理するため WAF を直接アタッチできません。上記設定は Web UI（CloudFront）と API（API Gateway）に適用されます。Runtime への不正アクセスを防ぐ主要な防御層は **JWT / IAM 認証** になります。

### その他の推奨事項

- **JWT トークンは環境変数経由で渡し、`mcp.json` に平文で書かない**
- **Cognito を使う場合、許可クライアント ID (`allowedClients`) を必要最小限にする**
- **本番利用では CloudTrail を有効化し、Runtime へのアクセスを監査ログに残す**
- **CORS 設定を自社ドメインに絞る**

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

## オプション 3: Generative AI Use Cases on AWS (GenU) 連携

> **注意:** [Generative AI Use Cases on AWS (GenU)](https://github.com/aws-samples/generative-ai-use-cases-jp) は活発に開発が行われている別のオープンソースプロジェクトです。以下の手順は 2026 年 4 月時点の GenU v5.x に基づいており、今後のリリースで変更される可能性があります。

[GenU](https://github.com/aws-samples/generative-ai-use-cases-jp) は、多様な生成 AI ユースケースを AWS 上で提供するオープンソース Web アプリケーションです。GenU の **AgentBuilder** を使うと、選択した MCP ツールとカスタムシステムプロンプトでエージェントを作成できます。AgentCore Runtime コンテナに spec-driven-presentation-maker をバンドルすることで、GenU の Web インターフェースからプレゼンテーションを生成できます。

### 前提条件

- GenU リポジトリがクローン済みでデプロイ可能な状態（[GenU README](https://github.com/aws-samples/generative-ai-use-cases-jp) 参照）
- ビルドマシンで Docker が利用可能（AgentCore コンテナイメージのビルドに必要）
- x86_64 ホスト（Intel/AMD）では、デプロイ前に `docker run --privileged --rm tonistiigi/binfmt --install arm64` を実行（AgentCore は ARM64 コンテナイメージを要求）
- `packages/cdk/cdk.json` または `parameter.ts` で **AgentBuilder を有効化**: `agentBuilderEnabled: true`

### Step 1: sdpm ファイルを GenU AgentCore Runtime ディレクトリにコピー

```bash
GENU_RUNTIME_DIR=<path-to-genu>/packages/cdk/lambda-python/generic-agent-core-runtime

cp -r <path-to-sdpm>/skill $GENU_RUNTIME_DIR/sdpm-skill
cp -r <path-to-sdpm>/mcp-local $GENU_RUNTIME_DIR/sdpm-mcp-local
```

### Step 2: Dockerfile のパッチ

`$GENU_RUNTIME_DIR/Dockerfile` の `EXPOSE` 行の**前**に以下を追加します：

```dockerfile
# --- SDPM: spec-driven-presentation-maker ---
COPY sdpm-skill/ ./sdpm-skill/
COPY sdpm-mcp-local/ ./sdpm-mcp-local/
RUN uv pip install --python /tmp/.venv/bin/python ./sdpm-skill
RUN /tmp/.venv/bin/python sdpm-skill/scripts/download_aws_icons.py \
 && /tmp/.venv/bin/python sdpm-skill/scripts/download_material_icons.py
RUN ln -s /var/task/sdpm-skill /var/task/skill
```

### Step 3: MCP サーバーの登録

`$GENU_RUNTIME_DIR/mcp-configs/agent-builder/mcp.json` の `mcpServers` に以下を追加します：

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

`SDPM_OUTPUT_DIR` は生成ファイルの出力先を指定します。GenU は `/tmp/ws` 配下のファイルのみ S3 にアップロードできるため、この設定が必要です。

### Step 4: デプロイ

```bash
cd <path-to-genu>
npx -w packages/cdk cdk deploy --all
```

### Step 5: AgentBuilder でエージェントを作成

GenU の AgentBuilder UI で：

1. MCP サーバーリストから `spec-driven-presentation-maker` を選択
2. 以下のシステムプロンプトを設定：

```
あなたはプレゼンテーション設計アシスタントです。spec-driven-presentation-maker の MCP ツールを使って PowerPoint スライドを作成してください。

重要なルール:
- デザインの決定を行う前に、必ず read_workflows を呼び出してワークフローを読み込んでください。
- プレゼンテーション JSON の書き込みには write_file ツールを使い、/tmp/ws/ に出力してください。Code Interpreter は使わないでください — サンドボックスが MCP ツールと分離されています。
- 大きな JSON はタイムアウトを避けるため分割して書いてください。各スライドを別ファイルとして書き出し（例: /tmp/ws/part1.json, /tmp/ws/part2.json）、最後に concat_files で /tmp/ws/presentation.json に結合してください。
- 分割の例:
  1. write_file("/tmp/ws/header.json", '{"template":"sample_template_dark","slides":[', mode="create")
  2. write_file("/tmp/ws/slide1.json", '{...スライド1のJSON...},', mode="create")
  3. write_file("/tmp/ws/slide2.json", '{...スライド2のJSON...}', mode="create")
  4. write_file("/tmp/ws/footer.json", ']}', mode="create")
  5. concat_files(source_paths=["/tmp/ws/header.json","/tmp/ws/slide1.json","/tmp/ws/slide2.json","/tmp/ws/footer.json"], destination="/tmp/ws/presentation.json")
  6. generate_pptx(slides_json_path="/tmp/ws/presentation.json", template="sample_template_dark")
- JSON にエラーがある場合は、write_file の mode="str_replace" で該当箇所だけ修正してください。ファイル全体を書き直す必要はありません。
- PPTX 生成後、upload_file_to_s3_and_retrieve_s3_url でアップロードし、S3 URL を Markdown リンク形式で提示してください: [ファイル名.pptx](S3_URL)
```

### 動作の仕組み

```
ユーザー → GenU AgentBuilder UI → Strands Agent (AgentCore Runtime)
                                     ├── sdpm MCP ツール (stdio)
                                     │   ├── generate_pptx → /tmp/ws/*.pptx
                                     │   └── search_assets, analyze_template, ...
                                     ├── write_file, concat_files (組み込み)
                                     └── upload_file_to_s3_and_retrieve_s3_url
                                         └── S3 URL → ユーザー
```

### 大きなファイルの書き込み

LLM の出力は1回のツール呼び出しで大きな JSON を生成するとタイムアウトする場合があります。これを回避するには：

1. `write_file` で各パーツを別ファイルとして書き出す
2. `concat_files` で最終ファイルに結合する
3. エラー修正には `write_file` の `mode="str_replace"` を使い、全体の書き直しを避ける
