[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# はじめに

spec-driven-presentation-maker をローカル利用から AWS デプロイまで、段階的にセットアップする手順を説明します。

## 前提条件

すべてのレイヤーで共通:

- Python 3.10 以上
- [uv](https://docs.astral.sh/uv/getting-started/installation/) パッケージマネージャー

Layer 3〜4（AWS デプロイ）を行う場合は追加で以下が必要です:

- AWS アカウント（[CDK ブートストラップ](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html)済み: `cdk bootstrap aws://ACCOUNT_ID/REGION`）
- Node.js 18 以上
- Docker または [Finch](https://github.com/runfinch/finch)（コンテナビルド用）
- AWS CLI（適切な認証情報を設定済み）

---

## Layer 1: Kiro CLI スキル

最もシンプルな使い方です。`skill/` ディレクトリを Kiro CLI のスキルディレクトリにコピーするだけで動作します。

```bash
# 依存関係のインストール
cd skill
uv sync

# アイコンのダウンロード（任意、推奨）
uv run python3 scripts/download_aws_icons.py
uv run python3 scripts/download_material_icons.py

# 動作確認
uv run python3 scripts/pptx_builder.py examples
```

エンジン、リファレンス（デザインパターン・ワークフロー・ガイド）、サンプルテンプレート（dark/light）、SKILL.md がすべて含まれています。

---

## Layer 2: ローカル MCP サーバー

spec-driven-presentation-maker を MCP 対応の任意のクライアントに接続します。AWS アカウントは不要です。

### サーバーの起動

```bash
cd mcp-local
uv sync
uv run python server.py
```

### MCP クライアントの設定

クライアントの MCP 設定ファイル（`claude_desktop_config.json`、`.vscode/mcp.json` 等）に以下を追加します。

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-local", "python", "server.py"]
    }
  }
}
```

### 動作確認

エージェントに「プレゼンテーションを作って」と依頼してください。以下のワークフローが自動的に実行されます。

1. MCP Server Instructions からワークフローファイルを読み取り
2. トピック・対象者・目的についてヒアリング
3. ブリーフィング → アウトライン → アートディレクションを設計し、`specs/` に永続化
4. スライドを 1 枚ずつ構築
5. PPTX を生成し、プレビューを表示

利用可能なツールの一覧は[アーキテクチャ — MCP ツール一覧](architecture.md#mcp-ツール一覧)を参照してください。

---

## Layer 3: リモート MCP サーバー（AWS）

spec-driven-presentation-maker を Amazon Bedrock AgentCore Runtime 上のリモート MCP サーバーとしてデプロイします。

> **💡 簡単デプロイ:** ローカルに CDK や Docker を用意せず、CloudShell からワンコマンドでデプロイすることもできます。
> [CloudShell デプロイ手順](deploy-cloudshell.md)を参照してください。

### 設定

```bash
cd infra
npm install
cp config.example.yaml config.yaml
```

`config.yaml` を編集して、デプロイするスタックを選択します。

#### Layer 3 — MCP Server のみ（最小構成）

```yaml
stacks:
  data: true           # 必須 — DynamoDB + S3
  runtime: true        # 必須 — AgentCore Runtime MCP Server
  pngWorker: true      # 任意 — PPTX→PNG 変換（Fargate + SQS）
  agent: false
  webUi: false

features:
  searchSlides: false   # セマンティックスライド検索（Bedrock Knowledge Base が必要）
```

### デプロイ

```bash
# Docker Desktop 使用時
npx cdk deploy --all

# Finch 使用時（Docker Desktop なし）
CDK_DOCKER=finch npx cdk deploy --all

# CI/CD 環境（対話なし）
CDK_DOCKER=finch npx cdk deploy --all --require-approval never
```

デプロイには 15〜30 分程度かかります。

#### モデル ID の変更

デフォルトでは `global.anthropic.claude-sonnet-4-6` が使用されます。別のモデルを使う場合は `infra/config.yaml` を編集:

```yaml
model:
  modelId: "global.anthropic.claude-opus-4-6-v1"
```

またはデプロイ時にオーバーライド:

```bash
npx cdk deploy --all --context modelId=global.anthropic.claude-opus-4-6-v1
```

### デプロイされるスタック（Layer 3）

| スタック | リソース |
|---------|---------|
| SdpmData | Amazon DynamoDB テーブル、S3 バケット（pptx + リソース）、リファレンスファイルを S3 にデプロイ |
| SdpmRuntime | Amazon Bedrock AgentCore Runtime エンドポイント、ECR リポジトリ + Docker イメージ、Amazon Cognito M2M 認証 |
| SdpmPngWorker | AWS Fargate タスク定義、SQS キュー、ECS クラスター |

### テンプレートの登録

CDK はテンプレートファイルを S3 にデプロイしますが、`list_templates` で表示するには Amazon DynamoDB への登録が必要です。
詳細は[カスタムテンプレート — テンプレートの登録（Layer 3）](custom-template.md#layer-3リモート-mcp)を参照してください。

### デプロイの確認

#### OAuth トークンの取得

```bash
TOKEN=$(curl -s -X POST \
  "https://<CognitoDomain>.auth.<region>.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "<M2MClientId>:<M2MClientSecret>" \
  -d "grant_type=client_credentials&scope=sdpm/invoke" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

`CognitoDomain`、`M2MClientId`、`M2MClientSecret` は CDK 出力から取得してください。

#### tools/list の呼び出し

```bash
ENCODED_ARN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('<RuntimeArn>', safe=''))")

curl -X POST \
  "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/${ENCODED_ARN}/invocations?qualifier=DEFAULT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}'
```

レスポンスにツール一覧が表示されれば成功です。

---

## Layer 4: フルスタック（AWS）

> **💡 簡単デプロイ:** Layer 4 も CloudShell からワンコマンドでデプロイできます。`./scripts/deploy.sh --region us-east-1` を実行するだけです。
> [CloudShell デプロイ手順](deploy-cloudshell.md)を参照してください。

`config.yaml` で `agent` と `webUi` を有効にしてデプロイすると、以下が追加されます。

- Strands Agent（Amazon Bedrock AgentCore Runtime 上）
- React Web UI（チャットインターフェース + デッキプレビュー）
- JWT Bearer 認証（デフォルト Amazon Cognito、任意の OIDC IdP に対応）

### 設定

```yaml
stacks:
  data: true
  runtime: true
  pngWorker: true
  agent: true          # Strands Agent（AgentCore Runtime 上）
  webUi: true          # React Web UI（S3 + CloudFront）

features:
  searchSlides: false
```

```bash
npx cdk deploy --all
```

### デプロイされるスタック（Layer 4 追加分）

| スタック | リソース |
|---------|---------|
| SdpmAuth | Amazon Cognito User Pool、ホスト UI |
| SdpmAgent | Strands Agent（Amazon Bedrock AgentCore Runtime 上）、ECR イメージ |
| SdpmWebUi | S3 バケット、Amazon CloudFront ディストリビューション、Amazon API Gateway、Lambda |

### 認証オプション

#### デフォルト: Amazon Cognito User Pool

`agent` または `webUi` を有効にすると、CDK が Amazon Cognito User Pool（ホスト UI 付き）を自動作成します。ユーザーは Web UI からサインインし、JWT がスタック全体に伝播されます。

認証・認可モデルの設計詳細は[アーキテクチャ — 認証・認可モデル](architecture.md#認証認可モデル)を参照してください。

#### 外部 OIDC IdP

自社の IdP（Entra ID、Auth0、Okta 等）を使う場合:

1. AuthStack をスキップするか、Amazon Cognito の Federation 機能で外部 IdP を接続
2. `config.yaml` に `oidcDiscoveryUrl` と `allowedClients` を設定
3. Runtime の `customJwtAuthorizer` が OIDC 準拠の任意の発行者からの JWT を検証

### Web UI の更新

Web UI のコードを変更した場合、フル CDK デプロイなしで更新できます。

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

`aws-exports.json`（認証情報・API エンドポイント等）は CDK の Custom Resource が管理しています。
スタック構成を変更した場合は `npx cdk deploy SdpmWebUi` を実行してください。

---

## オプション機能

### セマンティックスライド検索

`features.searchSlides: true` を設定すると、Amazon Bedrock Knowledge Base が作成され、デッキ横断のセマンティック検索が利用可能になります。

事前準備として、デプロイリージョンで Amazon Titan Text Embeddings V2 モデルへのアクセスを有効化してください（Amazon Bedrock コンソール → Model access）。

### カスタムテンプレート・アセット

独自の .pptx テンプレートやアイコンの追加方法は[カスタムテンプレートとアセット](custom-template.md)を参照してください。

---

## 注意事項

### コスト

- PngWorkerStack は NAT Gateway を含む VPC を作成します（時間課金が発生）
- Amazon Bedrock AgentCore Runtime は 2 つのコンテナ（Agent + MCP Server）を実行します
- `features.searchSlides` を有効にすると Amazon Bedrock Knowledge Base が追加で作成されます
- 開発・検証が終わったら `npx cdk destroy --all` でリソースを削除してください

### データ保持

DataStack の Amazon DynamoDB テーブルと S3 バケットは `RemovalPolicy.RETAIN` が設定されています。`cdk destroy` してもデータは削除されません。手動で削除する必要があります。

---

## トラブルシューティング

### Docker ビルドが Finch で失敗する

```bash
export CDK_DOCKER=finch
```

### ECR 権限エラーでデプロイが失敗する

Amazon Bedrock AgentCore Runtime が ECR からイメージを取得する際に権限エラーが発生する場合があります。通常は再デプロイで解決します。

```bash
npx cdk deploy --all
```

### list_templates にテンプレートが表示されない

CDK デプロイ後に `upload_template.py` を実行してください。CDK は .pptx ファイルを S3 にデプロイしますが、Amazon DynamoDB レコードは作成しません。

### .dockerignore が見つからない

Docker ビルドが極端に遅い、またはディスク容量エラーで失敗する場合は、リポジトリルートに `.dockerignore` が存在し、`infra/cdk.out/` が含まれていることを確認してください。

### Agent がワークフローに従わない

Strands SDK v1.30.0 以降で `server_instructions` が自動注入されます。`strands-agents>=1.30.0` がインストールされているか確認してください。

### Amazon CloudFront URL にアクセスすると白い画面が表示される

`web-ui/build` が存在しない状態でデプロイした可能性があります。

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

---

## 関連ドキュメント

- [アーキテクチャ](architecture.md) — 4 層構成、データフロー、認証モデル
- [カスタムテンプレート](custom-template.md) — テンプレートとアセットの追加
- [エージェント接続](add-to-gateway.md) — Amazon Bedrock AgentCore Gateway への接続方法
