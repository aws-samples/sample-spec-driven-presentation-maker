[EN](README.md) | [JA](README_ja.md)

# Spec-Driven Presentation Maker

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)
[![AWS Blog](https://img.shields.io/badge/AWS%20Blog-read-orange?logo=amazonaws)](https://aws.amazon.com/jp/blogs/news/spec-driven-presentation-maker-ja/)

仕様駆動開発のアプローチでプレゼンテーション資料を作成するオープンソースツールキット。
「何を伝えるか」を先に設計し、「どう見せるか」を AI が構築します。

> 📝 コンセプトと背景は AWS ブログ [Spec-Driven Presentation Maker — 伝えたいことを先に設計し、スライド構築は AI に任せる](https://aws.amazon.com/jp/blogs/news/spec-driven-presentation-maker-ja/) もあわせてご覧ください。

<!-- TODO: デモ GIF/動画を撮影後に差し替え -->
<!-- ![Demo](docs/images/demo.gif) -->

---

## 仕様駆動プレゼンテーションとは

従来の資料作成は「スライドを開いて、考えながら埋める」アプローチです。
構成が定まらないまま見た目の調整に時間を取られ、伝えたいメッセージがぼやけがちです。

仕様駆動プレゼンテーションは、ソフトウェア開発の仕様駆動開発（Spec-Driven Development）を資料作成に応用します。

| | 従来の資料作成 | 仕様駆動プレゼンテーション |
|---|---|---|
| 起点 | 白紙のスライド | ソース資料・要件 |
| 設計 | 作りながら考える | 先に論理構造を設計書として定義 |
| 構築 | 手作業でレイアウト | AI がテンプレートに準拠して自動構築 |
| 品質 | 属人的 | 設計書に基づくレビュー可能なプロセス |

### ワークフロー


![workflow](./docs/assets/workflow-ja.png)

---

## クイックスタート

利用環境に応じたセットアップ手順を参照してください:

| 環境 | セットアップ |
|---|---|
| エージェントスキル（Claude Code, Codex CLI, Cursor, Kiro, Copilot） | [はじめに — Layer 1](docs/ja/getting-started.md#layer-1-kiro-cli-スキル) |
| ローカル MCP クライアント（Claude Desktop, Claude Cowork） | [はじめに — Layer 2](docs/ja/getting-started.md#layer-2-ローカル-mcp-サーバー) |
| リモート MCP / Web UI（AWS デプロイ） | [デプロイ手順](docs/ja/deploy-cloudshell.md) |

### 🧩 Claude Code プラグイン（ワンコマンド導入）

Claude Code ユーザーはプラグインで一括導入できます（手動の MCP 設定は不要）。プラグインは
**ローカル MCP サーバー**・**オーケストレーター skill**・スライドを並列生成する
**compose サブエージェント** をまとめて登録します。

**事前インストール（プラグインには同梱できません。初回のみ各自で導入）:**

- [`uv`](https://docs.astral.sh/uv/) を `PATH` に — ローカル MCP サーバーを起動し、初回起動時に
  Python 依存を透過解決します（コールドスタートは数十秒）。
- **LibreOffice** と **poppler** — スライドプレビュー（HTML/SVG → PNG）の描画に必要です。

**導入（自動 — リポジトリDL・MCP/skill/サブエージェント登録まで完了）:**

```bash
# Claude Code 内で実行:
/plugin marketplace add aws-samples/sample-spec-driven-presentation-maker
/plugin install sdpm@sdpm
```

`/plugin install` でリポジトリがクローンされ（`mcp-local/`・`skill/` も同梱DL）、`uv` 経由で
`sdpm` MCP サーバーが自動起動し、`sdpm` skill と `sdpm:sdpm-composer` サブエージェントが登録
されます。`/plugin list`・`/mcp`（`sdpm` 接続）・`/agents`（`sdpm:sdpm-composer` 表示）で確認
してください。あとは「〇〇のスライドを作って」と頼むだけで、skill が briefing → outline →
art direction を進め、Phase 2（compose）を複数の composer サブエージェントへ並列委譲し、
review まで実施します。

> **どの入口を使う？** **Kiro CLI** → Layer 1 の skill。**Claude Desktop / その他 MCP
> クライアント** → Layer 2 のローカル MCP サーバー。**Claude Code** → このプラグイン（同じ
> Layer 2 MCP サーバーを CC ネイティブの skill + 並列 compose サブエージェントで包んだもの）。

### 🚀 AWS アカウントだけですぐに開始！ ワンクリックデプロイ

| リージョン | デプロイ |
|-----------|---------|
| 東京 (ap-northeast-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://ap-northeast-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| バージニア北部 (us-east-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-east-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| オレゴン (us-west-2) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-west-2.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |

パラメータの詳細や別のデプロイ方法については [デプロイ手順](docs/ja/deploy-cloudshell.md) を参照してください。

---

## ワークショップ

様々なシチュエーションでスライドを作成するためのサンプルデータを用意したハンズオンワークショップです。URL・PDF・CSV・議事録などからのスライド生成を実践できます。製造業、金融、ヘルスケア、IT など業界別シナリオも収録しています。

📖 **[ワークショップ](https://catalog.us-east-1.prod.workshops.aws/workshops/a275330a-0ae0-40b2-ad35-264e263c3882/ja-JP)**

---

## アーキテクチャ

4 層アーキテクチャで構成されています。各レイヤーは前のレイヤーの薄いラッパーです。必要なレイヤーだけ選んで使えます。

| ユースケース | レイヤー | AWS |
|---|---|:---:|
| Kiro CLI で個人利用 | Layer 1: `skill/` | 不要 |
| ローカル MCP（Claude Desktop, VS Code, Kiro） | Layer 2: `skill/` + `mcp-local/` | 不要 |
| チームデプロイ | Layer 3: + `mcp-server/` + `infra/` | 必要 |
| フルスタック | Layer 4: + `agent/` + `api/` + `web-ui/` | 必要 |

詳細は[アーキテクチャ](docs/ja/architecture.md)を参照してください。

---

## ドキュメント

| ドキュメント | 説明 |
|---|---|
| [アーキテクチャ](docs/ja/architecture.md) | 4 層構成、データフロー、認証モデル、MCP ツール一覧 |
| [はじめに](docs/ja/getting-started.md) | Layer 1〜4 のセットアップとデプロイ手順 |
| [推奨デプロイ手順](docs/ja/deploy-cloudshell.md) | AWS デプロイの推奨手順（CloudShell・ローカル Linux/macOS/WSL 対応、CDK/Docker 不要） |
| [エージェント接続](docs/ja/add-to-gateway.md) | MCP クライアントの接続方法 |
| [Teams・Slack 連携](docs/ja/teams-slack-integration.md) | チャットプラットフォーム連携 |
| [テンプレート・アセット](docs/ja/custom-template.md) | カスタムテンプレートとアセットの追加 |
| [コスト試算](docs/ja/cost.md) | 月額コストの内訳と最適化 |
| [削除手順](docs/ja/uninstall.md) | デプロイ済み AWS リソースの削除 |
| [Web UI（ローカルモード — 実験的機能）](web-ui/README_ja.md#local-mode) | Kiro CLI ACP をバックエンドにローカル環境で Web UI を動作させる（AWS 不要） |

---

## ディレクトリ構成

```
spec-driven-presentation-maker/
├── skill/            Layer 1 — エンジン、リファレンス、テンプレート
├── mcp-local/        Layer 2 — ローカル stdio MCP サーバー
├── mcp-server/       Layer 3 — Streamable HTTP MCP サーバー（LibreOffice 内蔵）
├── infra/            Layer 3-4 — CDK スタック
├── agent/            Layer 4 — Strands Agent
├── api/              Layer 4 — 統合 REST API Lambda
├── web-ui/           Layer 4 — React Web UI
├── shared/           共有モジュール（認可・スキーマ）
├── scripts/          デプロイ・運用ヘルパー
├── tests/            ユニットテスト
└── docs/             ドキュメント
```

---

## テスト

```bash
make all    # リント + ユニットテスト
make test   # ユニットテストのみ
make lint   # ruff リントのみ
```

---

## Contributing

コントリビューションを歓迎します。詳細は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## Code of Conduct

This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).

## Security

これはデモおよび教育目的のサンプルコードであり、本番環境での使用を想定していません。
デプロイ前に、組織のセキュリティ・規制・コンプライアンス要件を満たすよう、
セキュリティチームおよび法務チームと確認してください。

### 実装済みセキュリティ対策

- **S3 バケット**: パブリックアクセスブロック、サーバーサイド暗号化（SSE-S3）、バージョニング有効
- **DynamoDB**: 保存時暗号化、ポイントインタイムリカバリ有効
- **転送中データ**: すべての通信を TLS で暗号化
- **IAM**: サービスごとにスコープされた最小権限ロール、ワイルドカードリソース権限なし
- **API Gateway**: 全エンドポイントに Cognito JWT 認可
- **CloudFront**: Origin Access Identity（OAI）、HTTPS のみ、セキュリティヘッダー
- **シークレット**: ハードコードされた認証情報なし、環境変数または IAM ロール経由
- **AI/GenAI**: モデル出力は AI 生成として明示、データセットコンプライアンス文書化済み
- **ログ**: CloudWatch Logs（保持期間設定可能）、Bedrock 呼び出しログ（オプション）

### 環境依存の設定事項（デフォルトでは適用されません）

以下の項目は組織の環境、ネットワーク構成、セキュリティポリシーに依存するため、サンプルスタックとして安全にデフォルト適用できません。本番利用前に個別に評価してください。

1. **AWS CloudTrail** — アカウント単位の設定。既存の CloudTrail 設定への影響を避けるため個別に有効化
2. **S3・DynamoDB の VPC エンドポイント** — VPC 内にデプロイする場合のみ関連（このスタックは VPC を使用しない）
3. **AWS WAF による IP 制限** — 組み込みサポート済み。IP 範囲は環境依存のため、`config.yaml` の `waf.allowedIpV4AddressRanges` / `waf.allowedIpV6AddressRanges` または `deploy.sh` の `--waf-ipv4` / `--waf-ipv6` で指定
4. **CORS の限定** — 提供ドメインに依存
5. **S3 アクセスログ** — 保管先バケットと保持期間は利用者の選択
6. **Cognito 高度なセキュリティ（MFA、漏洩認証情報検出）** — デモ利用の摩擦を減らすためデフォルト無効
7. **Bedrock モデル・リージョン選定** — データ主権要件がある場合はクロスリージョン推論プロファイルを避ける

### 脆弱性の報告

潜在的な脆弱性を発見した場合は、GitHub の公開 Issue を作成せず、[CONTRIBUTING.md](CONTRIBUTING.md#security-issue-notifications) の手順に従って報告してください。

## License

This project is licensed under the [MIT-0 License](LICENSE).
