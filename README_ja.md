[EN](README.md) | [JA](README_ja.md)

# Spec-Driven Presentation Maker

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)

仕様駆動開発のアプローチでプレゼンテーション資料を作成するオープンソースツールキット。
「何を伝えるか」を先に設計し、「どう見せるか」を AI が構築します。

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

> **🚀 まずは試してみたい？** CloudShell から数分でフルスタックデプロイできます。ローカルに CDK や Docker は不要です。
> [CloudShell デプロイ手順](docs/ja/deploy-cloudshell.md)を参照してください。

### Layer 1: Kiro CLI スキル

`skill/` を Kiro CLI のスキルディレクトリにコピーするだけで使えます。

エンジンを Python パッケージとしてインストールすることもできます:

```bash
# 最新版
pip install git+https://github.com/aws-samples/sample-spec-driven-presentation-maker.git#subdirectory=skill

# バージョン指定
pip install git+https://github.com/aws-samples/sample-spec-driven-presentation-maker.git@v0.1.0#subdirectory=skill
```

インストール済みバージョンの確認:

```python
import sdpm
print(sdpm.__version__)
```

### Layer 2: ローカル MCP サーバー

```bash
cd mcp-local && uv sync
```

MCP クライアントの設定に追加:

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-local", "python", "server.py"]
    }
  }
}
```

### Layer 3〜4: AWS デプロイ

```bash
cd infra
cp config.example.yaml config.yaml   # スタックの有効/無効を設定
npm install && npx cdk deploy --all
```

各レイヤーの詳細なセットアップ手順は[はじめに](docs/ja/getting-started.md)を参照してください。

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

### セキュリティアーキテクチャ

- **認証**: Cognito User Pool による JWT トークン認証（Layer 4）
- **認可**: API・ストレージ層でのリソースレベル RBAC
- **暗号化**: S3 サーバーサイド暗号化（SSE-S3）、DynamoDB 保存時暗号化
- **ネットワーク**: CloudFront + OAI による静的アセット配信、API Gateway + Cognito 認可

---

## ドキュメント

| ドキュメント | 説明 |
|---|---|
| [アーキテクチャ](docs/ja/architecture.md) | 4 層構成、データフロー、認証モデル、MCP ツール一覧 |
| [はじめに](docs/ja/getting-started.md) | Layer 1〜4 のセットアップとデプロイ手順 |
| [CloudShell デプロイ](docs/ja/deploy-cloudshell.md) | CloudShell からワンコマンドデプロイ（CDK/Docker 不要） |
| [エージェント接続](docs/ja/add-to-gateway.md) | Amazon Bedrock AgentCore Gateway と MCP クライアントの接続方法 |
| [Teams・Slack 連携](docs/ja/teams-slack-integration.md) | チャットプラットフォーム連携 |
| [テンプレート・アセット](docs/ja/custom-template.md) | カスタムテンプレートとアセットの追加 |

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

### データ保護
- すべてのS3バケットはサーバーサイド暗号化（SSE-S3）を使用
- DynamoDBテーブルはAWSマネージド暗号化を使用
- 転送中のすべてのデータはTLSで暗号化
- すべてのS3バケットでBlock Public Accessが有効

### 実装済みセキュリティ対策

- **S3 バケット**: パブリックアクセスブロック、サーバーサイド暗号化（SSE-S3）、バージョニング有効
- **DynamoDB**: 保存時暗号化、ポイントインタイムリカバリ有効
- **IAM**: サービスごとにスコープされた最小権限ロール、ワイルドカードリソース権限なし
- **API Gateway**: 全エンドポイントに Cognito JWT 認可
- **CloudFront**: Origin Access Identity（OAI）、HTTPS のみ、セキュリティヘッダー
- **シークレット**: ハードコードされた認証情報なし、環境変数または IAM ロール経由
- **AI/GenAI**: モデル出力は AI 生成として明示、データセットコンプライアンス文書化済み
- **ログ**: CloudWatch Logs（保持期間設定可能）、Bedrock 呼び出しログ（オプション）

### 本番デプロイ前の推奨事項

1. 監査ログ用に AWS CloudTrail を有効化
2. VPC 内で実行する場合は S3・DynamoDB の VPC エンドポイントを設定
3. CloudFront と API Gateway に AWS WAF ルールを設定
4. ドメインに合わせて CORS 設定を見直し
5. 全バケットで S3 アクセスログを有効化
6. Cognito の高度なセキュリティ機能（MFA、漏洩認証情報検出）を設定
7. Amazon Bedrock のモデルアクセスとリージョン設定を確認 — データ主権が懸念される場合はクロスリージョン推論プロファイルの使用を避けること

See [CONTRIBUTING.md](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This project is licensed under the [MIT-0 License](LICENSE).
