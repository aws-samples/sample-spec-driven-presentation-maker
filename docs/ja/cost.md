[EN](../en/cost.md) | [JA](../ja/cost.md)

# コスト試算

SDPM を AWS にデプロイした際の推定コストをまとめます。

> 2026 年 4 月時点の公開料金に基づく概算です。AWS の料金は変更される可能性があります。最新情報は各サービスの公式ページを参照してください: [Amazon Bedrock 料金](https://aws.amazon.com/bedrock/pricing/)、[AgentCore 料金](https://aws.amazon.com/bedrock/agentcore/pricing/)、[Amazon S3 料金](https://aws.amazon.com/s3/pricing/)、[DynamoDB 料金](https://aws.amazon.com/dynamodb/pricing/)。

## 全体試算

Layer 4 フルスタック（us-east-1）の試算です。社内チーム 10 人程度、月 20 デッキ生成を想定しています。

### 固定費（常時稼働）

| リソース | 推定月額 |
|---|---|
| CloudFront | ~$1 |
| Cognito User Pool | $0 |
| API Gateway REST + Lambda（API） | ~$1 |
| S3（3 バケット） | ~$1 |
| DynamoDB On-Demand | ~$1 |
| ECR（2 イメージ） | ~$1 |
| CloudWatch Logs | ~$1 |

### 従量費（利用量依存）

| リソース | 月 20 デッキ想定 |
|---|---|
| AgentCore Runtime（MCP Server + Agent） | ~$5-10 |
| Bedrock Claude Sonnet 4.6（Agent LLM） | ~$80-130 |
| AgentCore Code Interpreter | ~$1-3 |
| AgentCore Memory | ~$1 |
| スライド検索（Bedrock KB + Titan Embed V2 + S3 Vectors） | ~$0.01-0.05 |

### 合計

**月 $95〜145 程度**（利用量により変動）

## 固定費の発生を止めるには

SDPM を使わない期間も固定費は発生し続けます。不要になった場合は [削除手順](uninstall.md) に従ってリソースをクリーンアップしてください。

## 関連ドキュメント

- [はじめに](getting-started.md) — デプロイ構成とオプション
- [推奨デプロイ手順](deploy-cloudshell.md) — CloudShell またはローカルシェルからのデプロイ手順
- [削除手順](uninstall.md) — リソースのクリーンアップ
