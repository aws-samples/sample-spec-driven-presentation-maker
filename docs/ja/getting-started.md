[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# はじめに

SDPM はブラウザで使うことも、普段の AI エージェントに接続することもできます。どちらも
AWS アカウントなしでローカル利用できます。内部の 4 層構成については
[アーキテクチャ](../en/architecture.md#4-layer-architecture)を参照してください。

## インストール

1 コマンドで SDPM が `~/.sdpm` に入ります: git checkout、MCP サーバーの環境、アイコンカタログ、
`sdpm` ランチャー。同じ checkout がすべての面に使われます — MCP 経由の AI エージェントと、
必要ならブラウザ用 Web UI。更新するものも削除するものも 1 つです。

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash
```

```powershell
# Windows（PowerShell 5.1 / 7。CI での検証のみ）
irm https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.ps1 | iex
```

流れ:

1. 依存を確認し、無ければ導入を提案します: `git`、`uv`、そしてスライドプレビュー用の
   LibreOffice と poppler。プレビューは任意で、無くてもデッキは生成されます。
2. **What to install** — 2 行のチェックリスト: MCP サーバー（常に on）とブラウザ用 Web UI（既定 on、
   space で外す）。Web UI を含めると Node.js 20+ と Kiro CLI（そのエージェント基盤）を入れて UI を
   ビルド、外せば Node.js は不要。
3. `~/.sdpm/checkout` に clone し、サーバー環境を同期し、AWS / Material のアイコンカタログを取得。
4. **Connect SDPM to your MCP clients** — マシン上で見つかったクライアントのチェックリスト（全部 on）。
   不要なものを space で外し、enter で確定。結果が表で出ます: ✓ registered / – skipped（後でやる
   `sdpm register <client>` 付き）/ ✗ failed。外したクライアントには何も書きません。

再実行しても既存のインストールを修復するだけで、2 つ目は作りません。

### インストーラーのオプション

| オプション | 効果 |
|---|---|
| `--full` / `--mcp-only` | プロファイルの質問を省く |
| `--register` / `--no-register` | 検出した全クライアントに登録 / 設定を表示するだけ |
| `--agent-name NAME` | Kiro CLI エージェントの名前（既定 `sdpm`。`sdpm register` / 状態表示でも使われる） |
| `--non-interactive` | すべて yes（プロファイルは full） |
| `--skip-libreoffice`, `--skip-shortcut` | それらを省く |
| `--deps-only` | `git`・`uv`・LibreOffice・poppler だけ入れる（開発者の checkout 向け） |

環境変数版: `SDPM_PROFILE=full|mcp`、`SDPM_REGISTER=yes|no`、`SDPM_NON_INTERACTIVE=1`、
`SDPM_HOME`（既定 `~/.sdpm`）、`SDPM_LAUNCHER_DIR`（既定 `~/.local/bin`、Windows は
`%USERPROFILE%\bin`）。`curl … | bash -s -- --mcp-only` のようにオプションを渡せます。

## `sdpm` ランチャー

```
sdpm                    状態: 版、プロファイル、入っている面、接続済みクライアント
sdpm webui              ブラウザ用 Web UI を起動して開く
sdpm mcp                MCP サーバーを stdio で起動（ターミナルでの動作確認用）
sdpm register [CLIENT]  MCP クライアントに接続（検出クライアントのチェックリスト。--yes, --dry-run）
sdpm unregister         接続を解除
sdpm mcp-config [CLIENT]  このマシンのパス入りでクライアント設定を表示（--json, --all）
sdpm update [--with-webui]  main を取得して同期し、入っているものを再ビルド（Web UI の追加も）
sdpm doctor             環境チェック
sdpm uninstall          ~/.sdpm・ランチャー・ショートカットを削除。登録解除も提案
```

ランチャーは全 OS で同じです。`sdpm mcp` は人間用で、クライアントに渡す設定は `uv` と
checkout を直接指します（次節）。

## AI エージェントから使う（MCP）

`sdpm register` は各クライアント自身の CLI で（Kiro CLI は SDPM が所有するエージェントファイルを
作って）接続するので、既存の設定ファイルを手で編集しません:

| クライアント | `sdpm register` がすること |
|---|---|
| Kiro CLI | 専用エージェント `~/.kiro/agents/sdpm.json` を書く（MCP サーバー、ツール、並列 composer のための `@sdpm` と `use_subagent` の信頼設定。prompt テキストは無し）— `kiro-cli chat --agent sdpm` か `/agent sdpm` で開始。他のセッションには何も足さない。`--agent-name` で別名、自作のエージェントファイルには触れない |
| Claude Code | `claude mcp add --scope user sdpm -- …`。composer は Claude Code のサブエージェントとして動き、サーバーを継承します。sdpm ツールの承認は 1 回（「今後確認しない」）か、`claude --allowedTools "mcp__sdpm__*"` で起動。インストーラー以前の plugin `sdpm@sdpm` が残っていれば `sdpm register` が `claude plugin uninstall` を提案します — 残すと全ツールが二重に見えます |
| Visual Studio Code | `code --add-mcp …` |
| Codex（CLI / IDE 拡張 / ChatGPT デスクトップアプリ） | `codex mcp add sdpm -- …` |
| Cursor | 実パスで組み立てた `cursor://…/mcp/install` deep link を開く — 1 クリック。サブエージェント機構の無いクライアントでは 1 エージェントがグループごとに順に composer 役をこなします（役割文書に明記） |
| Kiro IDE、その他 | JSON と書き込み先ファイルを表示（Kiro IDE は `~/.kiro/settings/mcp.json`） |
| Claude Desktop | 代わりに [`sdpm.mcpb`](https://github.com/aws-samples/sample-spec-driven-presentation-maker/releases/latest/download/sdpm.mcpb) をダブルクリック |

どの設定も同じ 1 行で、絶対パスです:

```json
{
  "mcpServers": {
    "sdpm": {
      "command": "/Users/you/.local/bin/uv",
      "args": ["run", "--directory", "/Users/you/.sdpm/checkout/servers/local", "python", "server.py"]
    }
  }
}
```

絶対パスが重要です: Dock やスタートメニューから起動した GUI クライアントはシェルの `PATH` を
引き継ぎません。Kiro CLI では同じブロックがエージェントファイルの中にあります。旧構成でグローバル
`~/.kiro/settings/mcp.json` に SDPM が入っている場合、`sdpm register kiro-cli` がその項目（全セッションに
ツールが載る）と、旧インストーラーが生成した `sdpm-composer` エージェントの削除を提案します。`sdpm mcp-config` があなたのパスを埋めたこのブロックを表示するので、上の表に
無いクライアントにはそのまま貼ります。

あとはエージェントにスライドを頼むだけです。最初に呼ばれる `start_presentation` が、作業を導く
役割文書と使えるスタイル・テンプレートを返します — MCP サーバーだけで完全な構成です。モードを
明示するにはサーバーの prompt を使います: `sdpm-vibe`（素材から質問なし）、`sdpm-spec`（対話で
構成を固める）、`sdpm-style`、`sdpm-translate`（Claude Code `/mcp__sdpm__sdpm-vibe`、VS Code
`/mcp.sdpm.sdpm-vibe`、Kiro CLI `/sdpm-vibe`）。

スライドプレビューには LibreOffice と poppler が必要です。無くてもデッキは生成され、ビルド結果に
`preview: {"status": "unavailable", "install": "…"}` として OS 別の導入コマンドが載り、
エージェントがそれを伝えます。アイコンカタログが何らかの理由で無い場合は、サーバー初回起動時に
バックグラウンドで取得されます。

## ブラウザから使う（Web UI）

`sdpm webui` は Web UI をローカルモードで起動して開きます — `http://localhost:3000` の Next.js が
Kiro CLI と ACP で話します。初回の前に `kiro-cli login` を 1 度実行してください。インストーラーは
デスクトップショートカットも作ります。MCP のみ構成に Web UI を後から足すには
`sdpm update --with-webui`。詳細: [Web UI ローカルモード](../../web-ui/README_ja.md#local-mode)。

## AWS にデプロイする

チーム向けのリモート MCP サーバーまたはホスト型 Web UI には
[ワンクリックデプロイ](../en/deploy-cloudshell.md#one-click-deploy-recommended)を使用してください。
推奨経路は AWS CloudShell から実行でき、ローカルの CDK / Docker は不要です。開発・デバッグ用の
直接 CDK 手順は[開発者向けセットアップ](#開発者向けセットアップ)にあります。

## 開発者向けセットアップ

`~/.sdpm/checkout` ではなく自分の clone で作業するコントリビューター向け。

### checkout からローカル MCP サーバー

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash -s -- --deps-only
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
uv sync
(cd servers/local && uv sync)
uv run python3 sdpm/scripts/download_aws_icons.py
uv run python3 sdpm/scripts/download_material_icons.py
make smoke        # ローカルサーバーに tools/list + start_presentation
```

インストール版と自分の clone は**両方持って**構いません。`~/.sdpm` はユーザーが動かすもの、clone は
あなたが変更するもの。クライアントには clone を**インストール版の隣に**登録します:

```bash
make register-dev              # Kiro CLI: エージェント `sdpm-dev` → この checkout。他はクライアントごとに確認
make register-dev AGENT=sdpm-x CLIENTS=kiro-cli   # worktree ごとに 1 エージェント、1 クライアントだけ
make mcp-config-dev            # この checkout 用の設定を表示するだけ
```

`kiro-cli chat --agent sdpm-dev` で作業ツリー、`--agent sdpm` でインストール版が動きます。Web UI は登録不要です:
`servers/local` を自分の `web-ui/` からの相対で解決するので、`cd web-ui && npm run dev:local` で clone の
サーバーと ACP エージェントがホットリロード付きで動きます（`sdpm webui` が 3000 を使っていれば `PORT=3001`。
逆にインストール版を動かすなら `SDPM_WEBUI_PORT`）。

| | インストール版（ユーザーが使うもの） | 自分の clone |
|---|---|---|
| MCP（Kiro CLI） | `kiro-cli chat --agent sdpm` | `make register-dev` → `--agent sdpm-dev` |
| Web UI | `sdpm webui` | `cd web-ui && npm run dev:local` |
| 更新 | `sdpm update` | `git pull` — 編集は次のセッションから反映 |Claude Code の
`--scope user` はスコープ内でサーバー名が 1 つなので、clone はプロジェクトスコープの登録か
`claude --mcp-config …` のアドホック設定にし、user スコープの `sdpm` は置き換えないでください。

### MCP を使わないエージェントスキル

`sdpm/SKILL.md` は MCP 非対応のエージェント向けに CLI（`sdpm/scripts/pptx_builder.py`）を直接
操作します。`sdpm/` をエージェントの skills ディレクトリにコピーまたはシンボリックリンクすれば、
エンジン・参照資料・テンプレートがすべて含まれています。アーキテクチャ上の成果物であり、
推奨経路ではありません。

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
