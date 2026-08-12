[EN](README.md) | [JA](README_ja.md)

# Spec-Driven Presentation Maker

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)
[![CI](https://github.com/aws-samples/sample-spec-driven-presentation-maker/actions/workflows/ci.yml/badge.svg)](https://github.com/aws-samples/sample-spec-driven-presentation-maker/actions/workflows/ci.yml)
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

### 頼めること

新規デッキの作成以外にも、やりたいことを伝えるだけでエージェントが対応するワークフローに
自動でルーティングされます:

| 頼み方 | 動作 |
|---|---|
| 「〜のスライドを作って」 | 新規プレゼン作成（ブリーフィング → アウトライン → アートディレクション → コンポーズ → レビュー） |
| 「この PPTX を編集して」 | 既存 PPTX を編集可能なデッキとして取り込み |
| 「PowerPoint で手直ししたので続きを」 | 手編集の内容をデッキに同期 |
| 「〜みたいなスタイルを作って」 | 再利用可能なスタイルガイドを作成（配色・タイポグラフィ・装飾） |
| 「このデッキを英語に翻訳して」 | 元デッキはそのままに、言語違いの派生デッキを作成 |

---

## クイックスタート

統合面は MCP サーバー 1 つだけです。エージェントを接続してスライド作成を頼むだけ —
モードの振る舞いはサーバー自身が `start_presentation` ツールで配信します。
リポジトリ自体が [Agent Plugins](https://agent-plugins.org) 準拠のポータブルパッケージ
なので、この形式に対応したクライアントは MCP サーバーとモード入口をまとめて読み込めます。

| 環境 | セットアップ |
|---|---|
| Claude Code | `/plugin marketplace add aws-samples/sample-spec-driven-presentation-maker` → `/plugin install sdpm@sdpm` |
| Kiro CLI | このリポジトリを `git clone` して `make install-kiro` |
| Kiro IDE（Powers） | このチェックアウトを Power として導入 — Agent Plugins パッケージです |
| Codex | チェックアウトで `codex plugin marketplace add ./` → ChatGPT デスクトップアプリから導入 |
| Claude Desktop / 任意の MCP クライアント | `servers/local` を stdio MCP サーバーとして登録 — [はじめに](docs/ja/getting-started.md) 参照 |
| MCP なし | エージェントに [`sdpm/SKILL.md`](sdpm/SKILL.md) を読ませる — CLI を直接駆動します |
| チーム利用 / リモート MCP / Web UI（AWS） | [デプロイ手順](docs/en/deploy-cloudshell.md) |

**モードの選び方.** 「スライドにして」と頼むだけで十分です（エージェントが
`start_presentation` を呼んで選びます）。明示的に選ぶなら入口を使ってください:
`sdpm-vibe`（手元の素材から高速生成）、`sdpm-spec`（対話設計・各ステップで承認）、
`sdpm-style`（再利用できるスタイルガイド作成）、`sdpm-translate`（既存デッキの他言語翻訳）。
skill をスラッシュコマンドにする
クライアントでは `/sdpm-vibe` `/sdpm-spec` `/sdpm-style` `/sdpm-translate` として使えます。入口は該当
ペルソナをサーバーから読み込むだけで、振る舞いの実体は `personas/` の 1 箇所のままです。

**ローカル利用の前提:** [`uv`](https://docs.astral.sh/uv/) が `PATH` にあること。
スライドプレビュー（PNG 描画）には **LibreOffice** と **poppler** も必要です。

**チェックアウトはそのまま置いてください:** Claude Code / Kiro / ローカル MCP は
チェックアウトからサーバーを起動します（`uv run --directory <checkout>/servers/local`）。
更新は `git pull` だけ — ペルソナやナレッジはチェックアウトから直接読まれます。

> **v0.4 からのアップグレード:** ディレクトリ構成とインストール手順が変わりました —
> [v0.5 移行ガイド](docs/en/migration-v0.5.md) を参照してください。

---

## 🚀 AWS アカウントだけですぐに開始！ ワンクリックデプロイ

| リージョン | デプロイ |
|-----------|---------|
| 東京 (ap-northeast-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://ap-northeast-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| バージニア北部 (us-east-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-east-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| オレゴン (us-west-2) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-west-2.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |

パラメータの詳細や別のデプロイ方法については [デプロイ手順](docs/en/deploy-cloudshell.md) を参照してください。

---

## ワークショップ

様々なシチュエーションでスライドを作成するためのサンプルデータを用意したハンズオンワークショップです。URL・PDF・CSV・議事録などからのスライド生成を実践できます。製造業、金融、ヘルスケア、IT など業界別シナリオも収録しています。

📖 **[ワークショップ](https://catalog.us-east-1.prod.workshops.aws/workshops/a275330a-0ae0-40b2-ad35-264e263c3882/ja-JP)**

---

## アーキテクチャ

```
sdpm/        エンジン（json <-> pptx）+ ナレッジ（references, assets, templates）
personas/    モードの振る舞い — start_presentation(mode=...) で全 MCP クライアントに配信
skills/      モードの入口 — ペルソナをサーバーから読み込むだけの薄いディスパッチャ
plugin.json  Agent Plugins マニフェスト（+ mcp.json）— ルートをポータブルプラグインにする
servers/     local（stdio, AWS 不要）/ remote（HTTP, S3 + DynamoDB）— 単一ツールコントラクトの薄い bind
clients/     クライアント別の配線（Claude Code / Codex マニフェスト、Kiro インストーラ）
agent/ api/ infra/ web-ui/   オプションの AWS クラウドスタック（Strands Agent, REST API, CDK, React UI）
```

エージェントに必要なもの — ツール・ワークフロー・ガイド・モードの振る舞い — はすべて
MCP サーバーが配信します。クライアント側のファイルは最小限の配線（クライアント別マニフェストと、
何をするかは書かずモード名だけを指す入口）だけです。
全体像は [Architecture](docs/en/architecture.md) を参照してください。

---

## ドキュメント

詳細ドキュメントは英語版に一本化しています（日本語は README と「はじめに」のみ）。

| ドキュメント | 説明 |
|---|---|
| [はじめに（日本語）](docs/ja/getting-started.md) | 各環境のセットアップ手順 |
| [Getting Started](docs/en/getting-started.md) | Setup for every environment |
| [Architecture](docs/en/architecture.md) | レイヤー設計、データフロー、認証モデル、MCP ツール一覧 |
| [Migration to v0.5](docs/en/migration-v0.5.md) | v0.4 からの移行（パス変更、skills 廃止） |
| [Recommended Deploy](docs/en/deploy-cloudshell.md) | CloudShell からの AWS デプロイ（CDK/Docker 不要） |
| [Connecting Agents](docs/en/add-to-gateway.md) | MCP クライアントの接続方法 |
| [Teams & Slack Integration](docs/en/teams-slack-integration.md) | チャットプラットフォーム連携 |
| [Custom Templates & Assets](docs/en/custom-template.md) | カスタムテンプレートとアセットの追加 |
| [Cost Estimates](docs/en/cost.md) | 月額コストの内訳と最適化 |
| [Uninstall](docs/en/uninstall.md) | デプロイ済み AWS リソースの削除 |
| [Web UI（ローカルモード — 実験的機能）](web-ui/README_ja.md#local-mode) | Kiro CLI ACP をバックエンドにローカル環境で Web UI を動作させる（AWS 不要） |

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
