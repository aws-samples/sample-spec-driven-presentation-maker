[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# はじめに

SDPM はブラウザで使うことも、普段の AI エージェントに接続することもできます。どちらも
AWS アカウントなしでローカル利用できます。内部の 4 層構成については
[アーキテクチャ](../en/architecture.md#4-layer-architecture)を参照してください。

## 使い方を選ぶ

### ブラウザで使う（フル機能）

ローカル Web UI では、チャット、デッキ管理、編集可能なプレビュー、PowerPoint 出力を利用できます。
macOS / Linux では次の 1 行で導入します。

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash
```

git、uv、LibreOffice、poppler、Node.js、Kiro CLI の導入、
`${SDPM_HOME:-~/.sdpm}/checkout` への clone、Web UI のビルド、`sdpm` ランチャーと
デスクトップショートカットの作成まで自動で行います。`sdpm` または `sdpm launch` を実行すると
[http://localhost:3000](http://localhost:3000) が開きます。

Windows では次を実行します。

```powershell
irm https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.ps1 | iex
```

Windows 対応は CI でのみ検証済みで、Windows 実機での手動 QA は未実施です。

#### ランチャーコマンド

| コマンド | 動作 |
|---|---|
| `sdpm` / `sdpm launch` | ローカル Web UI を起動してブラウザで開く |
| `sdpm update` | `main` を取得し、依存関係を更新して Web UI を再ビルド |
| `sdpm check-update` | 新しいリビジョンがあるか確認 |
| `sdpm doctor` | リポジトリの環境チェックを実行 |
| `sdpm version` | 導入済みリビジョンを表示 |
| `sdpm path` | checkout のパスを表示 |
| `sdpm help` | コマンドヘルプを表示 |

#### インストーラーオプション

| macOS / Linux | Windows | 動作 |
|---|---|---|
| `--deps-only` | `-DepsOnly` | git、uv、LibreOffice、poppler だけを導入 |
| `--non-interactive` | `-NonInteractive` | 依存関係の導入確認を自動承認 |
| `--skip-libreoffice` | `-SkipLibreOffice` | LibreOffice の確認と導入を省略 |
| `--skip-shortcut` | `-SkipShortcut` | デスクトップショートカットを作成しない |

導入先を変更する場合は `SDPM_HOME` を設定します。既定値は Unix で `~/.sdpm`、
Windows で `%USERPROFILE%\.sdpm` です。

### いつもの AI エージェントから使う

クライアントを選び、表の操作を行ってください。`uvx` を使う経路は checkout が不要です。
初回は uv がパッケージをビルドしてキャッシュするため、数十秒かかることがあります。

| クライアント | 導入方法 |
|---|---|
| Claude Desktop | [`sdpm.mcpb` をダウンロード](https://github.com/aws-samples/sample-spec-driven-presentation-maker/releases/latest/download/sdpm.mcpb)してダブルクリック |
| Cursor | [![Add to Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](cursor://anysphere.cursor-deeplink/mcp/install?name=sdpm&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL2F3cy1zYW1wbGVzL3NhbXBsZS1zcGVjLWRyaXZlbi1wcmVzZW50YXRpb24tbWFrZXIjc3ViZGlyZWN0b3J5PXNlcnZlcnMvbG9jYWwiLCJzZHBtLW1jcCJdfQ==) |
| Visual Studio Code | `code --add-mcp '{"name":"sdpm","command":"uvx","args":["--from","git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local","sdpm-mcp"]}'` |
| Kiro CLI | `kiro-cli mcp add --name sdpm --command uvx --args '["--from","git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local","sdpm-mcp"]' --scope global` |
| Claude Code | `/plugin marketplace add aws-samples/sample-spec-driven-presentation-maker` → `/plugin install sdpm@sdpm` |
| Codex | チェックアウトで `codex plugin marketplace add ./` を実行し、ChatGPT デスクトップアプリから導入 |

`uvx` を使うクライアントでは、OS 依存を次の 1 行で導入できます。

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash -s -- --deps-only
```

LibreOffice と poppler は PNG プレビューの描画に使用します。未導入でも PPTX は生成できます。
Claude Desktop は Python ランタイムを管理し、`.mcpb` には公式アイコンカタログが同梱されます。

AWS / Material のアイコンカタログは、サーバー初回起動時にバックグラウンドで取得されます（約 40 MB。
完了までは `search_assets` が進行状況をエージェントに返します）。事前に取得したい場合や、実行時に
ネットワークが使えないホストでは次を実行します。

```bash
uvx --from "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local" sdpm-install-assets
```

既定の `uvx` コマンドは `main` を追従します。キャッシュ済みの checkout とパッケージを強制更新するには
次を実行します。

```bash
uvx --refresh --from "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local" sdpm-install-assets --help
```

導入後はエージェントに「〜のスライドを作って」と頼んでください。エージェントが最初に呼ぶ
`start_presentation` が、オーケストレーターの役割文書と使えるスタイル・テンプレートを返します。
スライドを書くサブエージェントは `start_composing`、スタイル作成は `start_style`、翻訳は
`start_translation` から始まります。MCP サーバーだけで完全な構成です — skill やエージェント定義は
任意の追加要素です。モードを明示するにはサーバーの prompt を使います: `sdpm-vibe`（素材から質問なし）、
`sdpm-spec`（対話で構成を固める）、`sdpm-style`、`sdpm-translate`（Claude Code `/mcp__sdpm__sdpm-vibe`、
VS Code `/mcp.sdpm.sdpm-vibe`、Kiro CLI `/sdpm-vibe`）。

## AWS にデプロイする

チーム向けのリモート MCP サーバーまたはホスト型 Web UI には
[ワンクリックデプロイ](../en/deploy-cloudshell.md#one-click-deploy-recommended)を使用してください。
推奨経路は AWS CloudShell から実行でき、ローカルの CDK / Docker は不要です。開発・デバッグ用の
直接 CDK 手順は[手動セットアップ](#手動セットアップ)にあります。

## 手動セットアップ

以下はコントリビューター、クライアントの高度な設定、AWS の直接開発向けです。2 つの
クイックスタートでは不要な実装詳細を含みます。

### MCP を使わないエージェントスキル

`sdpm/` を SKILL.md 対応エージェントの skills ディレクトリへコピーまたは symlink すると、
エンジンを直接利用できます。エージェントは `scripts/pptx_builder.py` を呼び出すため、MCP サーバーも
AWS アカウントも不要です。

```bash
cd sdpm
uv sync

# アイコンのダウンロード（任意、推奨）
uv run python3 scripts/download_aws_icons.py
uv run python3 scripts/download_material_icons.py

# 動作確認
uv run python3 scripts/pptx_builder.py list_templates
```

エンジン、リファレンス（ワークフロー・ガイド・同梱スタイル）、サンプルテンプレート（dark/light）、SKILL.md がすべて含まれています。

### ローカル MCP サーバー

AWS を使わず、SDPM を MCP 対応クライアントへ接続します。

#### checkout からの Kiro CLI 導入

クイックスタートの `kiro-cli mcp add … uvx …` 1 行で構成は完全です。オーケストレーターは通常の
サブエージェントとして composer を spawn し、composer は `start_composing` から始めます。
`make install-kiro` は checkout ベースの代替手段で、加えて `sdpm-*` skill（スラッシュコマンドの
入口）を link し、SDPM だけを MCP サーバーに持つ `sdpm-composer` エージェントを生成します —
MCP サーバーが多いプロファイル向けの最適化であり、必須ではありません。

```bash
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
make install-kiro
kiro-cli chat   # あとは「〜のスライドを作って」と頼むだけ
```

`sdpm` を `<KIRO_HOME>/settings/mcp.json`（既定は `~/.kiro`）へ登録し、入口を
`<KIRO_HOME>/skills/` へ link し、`<KIRO_HOME>/agents/sdpm-composer.json` を生成します。
composer profile はプロファイル内の全サーバーではなく、SDPM MCP サーバーだけを起動します。
checkout は移動せずに保持してください。更新は `git pull` で行い、移動した場合だけ
`make install-kiro` を再実行します。

```bash
uv run python3 clients/kiro/install.py --agent NAME       # 特定のエージェント設定に登録
uv run python3 clients/kiro/install.py --mode legacy      # Power 自動判定を使わない
KIRO_HOME=~/.kiro-sdpm-dev make install-kiro              # 別プロファイルに導入
```

別の checkout が配線を所有している場合、インストーラーは上書きせず停止します。別の
`KIRO_HOME` を使う、他方の配線を削除する、または意図的に切り替える場合だけ
`--replace-existing` を指定してください。

#### Kiro IDE Power

リポジトリルートは [Agent Plugins](https://agent-plugins.org) パッケージ
（`plugin.json`、`mcp.json`、`skills/`）です。Kiro IDE から checkout を Power として導入します。
同梱 MCP サーバーは Kiro がグローバルスコープで管理します。GitHub import URL は実機での検証が
別途必要なため、このガイドでは未検証のワンクリック URL を案内しません。

同じプロファイルで Power と checkout ベースの Kiro CLI 配線を同時に有効にしないでください。
別の `KIRO_HOME` を使います。Power があるプロファイルで `make install-kiro` を実行すると、
インストーラーは自身が作った旧配線を削除します。

#### checkout から Codex プラグインを導入

```bash
codex plugin marketplace add ./
```

checkout 内で実行し、ChatGPT デスクトップアプリから `spec-driven-presentation-maker` を導入して
新しい会話を開始します。Codex はプラグインを `~/.codex/plugins/cache/…` へコピーし、書き込み可能な
plugin data に Python 環境を作成します。

#### MCP の手動設定

clone 不要の構成では、次の stdio サーバー定義をクライアントへ追加します。

```json
{
  "mcpServers": {
    "sdpm": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local",
        "sdpm-mcp"
      ]
    }
  }
}
```

ソース checkout から起動する場合は、サーバーを準備して動作確認します。

```bash
cd servers/local
uv sync
uv run python server.py
```

クライアントの MCP 設定では、checkout の絶対パスを指定します。

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/servers/local", "python", "server.py"]
    }
  }
}
```

接続後に「プレゼンテーションを作って」と依頼してください。エージェントがワークフローを読み、
トピック・対象者・目的を確認し、ブリーフ、アートディレクション、アウトライン、スライドを作成して、
PPTX とプレビューを生成します。ツール一覧は
[アーキテクチャの MCP ツール一覧](../en/architecture.md#mcp-tool-reference)を参照してください。

### リモート MCP サーバー（AWS）

spec-driven-presentation-maker を Amazon Bedrock AgentCore Runtime 上のリモート MCP サーバーとしてデプロイします。

> **💡 AWS へのデプロイは [推奨デプロイ手順](../en/deploy-cloudshell.md) を推奨します。**
> `scripts/deploy.sh` は CloudShell と任意のローカル Linux/macOS から実行でき、CodeBuild 経由でデプロイされるため CDK/Docker のローカルインストールが不要です。本ページ以降の手順はローカル CDK を直接使う開発・デバッグ向けフローです。

#### 設定

```bash
cd infra
npm ci
cp config.example.yaml config.yaml
```

`config.yaml` を編集して、デプロイするスタックを選択します。

##### MCP Server のみ（最小構成）

```yaml
stacks:
  data: true           # 必須 — DynamoDB + S3
  runtime: true        # 必須 — AgentCore Runtime MCP Server
  agent: false
  webUi: false

features:
  enableInvocationLogging: false  # Bedrock Model Invocation Logging（任意）
```

#### デプロイ

```bash
# Docker Desktop 使用時
npx cdk deploy --all

# Finch 使用時（Docker Desktop なし）
CDK_DOCKER=finch npx cdk deploy --all

# CI/CD 環境（対話なし）
CDK_DOCKER=finch npx cdk deploy --all --require-approval never
```

デプロイには 15〜30 分程度かかります。

##### モデル ID の変更

デフォルトでは `global.anthropic.claude-sonnet-4-6` が使用されます。別のモデルを使う場合は `infra/config.yaml` を編集:

```yaml
model:
  modelId: "global.anthropic.claude-opus-4-6-v1"
```

またはデプロイ時にオーバーライド:

```bash
npx cdk deploy --all --context modelId=global.anthropic.claude-opus-4-6-v1
```

#### デプロイされるスタック

| スタック | リソース |
|---------|---------|
| SdpmData | Amazon DynamoDB テーブル、S3 バケット（pptx + リソース）、リファレンスファイルを S3 にデプロイ |
| SdpmRuntime | Amazon Bedrock AgentCore Runtime エンドポイント、ECR リポジトリ + Docker イメージ、Amazon Cognito M2M 認証 |

#### テンプレートの登録

CDK はテンプレートファイルを S3 にデプロイしますが、`list_templates` で表示するには Amazon DynamoDB への登録が必要です。
詳細は[カスタムテンプレート — テンプレートの登録](../en/custom-template.md#layer-3-remote-mcp)を参照してください。

#### デプロイの確認

##### OAuth トークンの取得

```bash
TOKEN=$(curl -s -X POST \
  "https://<CognitoDomain>.auth.<region>.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "<M2MClientId>:<M2MClientSecret>" \
  -d "grant_type=client_credentials&scope=sdpm/invoke" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

`CognitoDomain`、`M2MClientId`、`M2MClientSecret` は CDK 出力から取得してください。

##### tools/list の呼び出し

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

### フルスタック（AWS）

> **💡 推奨:** フルスタックのデプロイは [推奨デプロイ手順](../en/deploy-cloudshell.md) を利用してください（CloudShell と任意のローカル Linux/macOS で動作）。`./scripts/deploy.sh --region us-east-1` を実行するだけで、CDK/Docker のローカルインストールは不要です。

`config.yaml` で `agent` と `webUi` を有効にしてデプロイすると、以下が追加されます。

- Strands Agent（Amazon Bedrock AgentCore Runtime 上）
- React Web UI（チャットインターフェース + デッキプレビュー）
- JWT Bearer 認証（デフォルト Amazon Cognito、任意の OIDC IdP に対応）

#### 設定

```yaml
stacks:
  data: true
  runtime: true
  agent: true          # Strands Agent（AgentCore Runtime 上）
  webUi: true          # React Web UI（S3 + CloudFront）

features:
  enableInvocationLogging: false
```

```bash
npx cdk deploy --all
```

#### フルスタックで追加されるリソース

| スタック | リソース |
|---------|---------|
| SdpmAuth | Amazon Cognito User Pool、ホスト UI |
| SdpmAgent | Strands Agent（Amazon Bedrock AgentCore Runtime 上）、ECR イメージ |
| SdpmWebUi | S3 バケット、Amazon CloudFront ディストリビューション、Amazon API Gateway、Lambda |

#### 認証オプション

##### デフォルト: Amazon Cognito User Pool

`agent` または `webUi` を有効にすると、CDK が Amazon Cognito User Pool（ホスト UI 付き）を自動作成します。ユーザーは Web UI からサインインし、JWT がスタック全体に伝播されます。

認証・認可モデルの設計詳細は[アーキテクチャ — 認証・認可モデル](../en/architecture.md#authentication-and-authorization-model)を参照してください。

##### 外部 OIDC IdP

自社の IdP（Entra ID、Auth0、Okta 等）を使う場合:

1. AuthStack をスキップするか、Amazon Cognito の Federation 機能で外部 IdP を接続
2. `config.yaml` に `oidcDiscoveryUrl` と `allowedClients` を設定
3. Runtime の `customJwtAuthorizer` が OIDC 準拠の任意の発行者からの JWT を検証

#### デプロイ後のエンドポイント確認

デプロイスクリプトのログ監視が途中で中断した場合や、後からエンドポイントを確認したい場合は以下を実行してください。

```bash
bash scripts/show_endpoints.sh
```

デプロイ済みの CloudFormation スタックから CloudFront URL と Cognito サインアップ URL を表示します。

#### Web UI の更新

Web UI のコードを変更した場合、フル CDK デプロイなしで更新できます。

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

`aws-exports.json`（認証情報・API エンドポイント等）は CDK の Custom Resource が管理しています。
スタック構成を変更した場合は `npx cdk deploy SdpmWebUi` を実行してください。

---


## オプション機能

### WAF IP アドレス制限

`config.yaml` で `waf.allowedIpV4AddressRanges` および/または `waf.allowedIpV6AddressRanges` を設定すると、CloudFront と API Gateway へのアクセスを IP アドレスで制限できます。

```yaml
waf:
  allowedIpV4AddressRanges:
    - "10.0.0.0/8"
    - "192.168.0.0/16"
  allowedIpV6AddressRanges:
    - "2001:db8::/32"
```

設定すると、CDK は以下を作成します:
- **SdpmCloudFrontWaf** スタック（`us-east-1`、WAFv2 CLOUDFRONT スコープの要件）— CloudFront に関連付け
- **リージョナル WAF**（デプロイリージョン）— API Gateway に関連付け

デフォルトアクションは **Block** で、指定された IP 範囲のみアクセスが許可されます。`waf` セクションを省略した場合、WAF リソースは作成されません。

> **⚠️ IPv6 に関する注意:** `allowedIpV4AddressRanges` のみ指定し `allowedIpV6AddressRanges` を省略した場合、IPv6 によるアクセスはすべてブロックされます。最近のブラウザは IPv6 を優先的に使用するため、IPv4 アドレスが許可されていても Web UI が「Loading authentication configuration...」のまま停止することがあります。デュアルスタック環境では必ず IPv4 と IPv6 の両方を指定してください。

### セマンティックスライド検索

Amazon Bedrock Knowledge Bases と Amazon S3 Vectors を用いた、デッキ横断のセマンティック検索を標準機能として提供します。追加の設定は不要です。

### カスタムテンプレート・アセット

独自の .pptx テンプレートやアイコンの追加方法は[カスタムテンプレートとアセット](../en/custom-template.md)を参照してください。

---

## 注意事項

### コスト

コストの詳細は[コスト試算](../en/cost.md)を参照してください。開発・検証が終わったら `npx cdk destroy --all` でリソースを削除してください。

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

- [アーキテクチャ](../en/architecture.md) — 4 層構成、データフロー、認証モデル
- [カスタムテンプレート](../en/custom-template.md) — テンプレートとアセットの追加
- [エージェント接続](../en/add-to-gateway.md) — MCP クライアントの接続方法
