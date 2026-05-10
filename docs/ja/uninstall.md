[EN](../en/uninstall.md) | [JA](../ja/uninstall.md)

# 削除手順

SDPM をデプロイした AWS 環境からリソースを削除する手順です。

## 概要

SDPM は複数の CloudFormation スタックで構成されています。依存関係の都合上、単純な CloudFormation コンソール操作では手間がかかるため、[go-to-k/delstack](https://github.com/go-to-k/delstack) を使った一括削除を推奨します。

削除対象のスタック一覧（依存順に逆順で削除されます）:

- `SdpmWebUi`（Layer 4）
- `SdpmAgent`（Layer 4）
- `SdpmRuntime`
- `SdpmData`
- `SdpmAuth`（デフォルト Cognito 利用時）
- `SdpmCloudFrontWaf`（WAF 有効時、us-east-1 のみ）

## 推奨: delstack を使った一括削除

[go-to-k/delstack](https://github.com/go-to-k/delstack) は CloudFormation スタックを依存関係に応じて逆順で削除し、内部の S3 バケットや ECR リポジトリ等も確実にクリーンアップしてくれるツールです。

### インストール

macOS / Linux の場合:

```bash
brew install go-to-k/tap/delstack
```

Go 環境がある場合:

```bash
go install github.com/go-to-k/delstack@latest
```

その他の方法は [delstack の README](https://github.com/go-to-k/delstack#install) を参照してください。

### 削除コマンド

デプロイしたリージョン（例: `us-east-1`）で以下を実行します。

```bash
# Layer 4 フルスタックを削除
delstack --region us-east-1 \
  -s SdpmWebUi \
  -s SdpmAgent \
  -s SdpmRuntime \
  -s SdpmData \
  -s SdpmAuth

# WAF を有効化していた場合は追加で（us-east-1 固定）
delstack --region us-east-1 -s SdpmCloudFrontWaf
```

Layer 3 デプロイの場合は `SdpmWebUi`, `SdpmAgent` を省略してください。

### delstack の特徴

- **依存関係の自動解決**: スタック間の依存を自動で判定し、正しい順序で削除します
- **S3 バケットの強制削除**: バージョニング有効なバケットも中身を一括削除できます
- **ECR リポジトリの強制削除**: `DELETE_FAILED` になりがちな ECR リポジトリもクリーンに削除します
- **インタラクティブ確認**: 実行前に削除対象の一覧が表示され、`yes` 入力で実行されます

## CloudShell から実行する場合

AWS CloudShell には Go ランタイムが含まれているため、以下の手順で delstack を利用できます。

```bash
# CloudShell でインストール
go install github.com/go-to-k/delstack@latest

# 環境変数を通す
export PATH=$PATH:$(go env GOPATH)/bin

# 削除実行
delstack --region us-east-1 -s SdpmWebUi -s SdpmAgent -s SdpmRuntime -s SdpmData -s SdpmAuth
```

## CDK で削除する場合（ローカル環境のみ）

ローカルに CDK 環境がある場合は以下でも削除可能です。ただし S3 バケットや ECR リポジトリの残留により失敗しやすいため、delstack の利用を推奨します。

```bash
cd infra
npx cdk destroy --all
```

## CloudFormation コンソールから手動で削除する場合

GUI で操作したい場合は、以下の **逆順** でスタックを削除してください。

1. `SdpmWebUi`
2. `SdpmAgent`
3. `SdpmRuntime`
4. `SdpmData`
5. `SdpmAuth`
6. `SdpmCloudFrontWaf`（us-east-1 リージョンで確認）

S3 バケットや ECR リポジトリが残留して `DELETE_FAILED` になった場合は、該当リソースを手動で空にしてから再試行してください。

## 削除後の確認

削除後、以下のリソースが残っていないことを確認してください:

- CloudFormation: 上記スタックが表示されないこと
- S3: `sdpm-*`, `cdk-*` プレフィックスのバケット
- DynamoDB: `sdpm-*` テーブル
- ECR: `sdpm-*` リポジトリ
- SSM Parameter Store: `/sdpm/*`
- CloudWatch Logs: `/aws/lambda/sdpm-*`, `/aws/bedrock/*`

## 注意事項

- **データの復旧はできません**。デッキ・スライドデータを保管したい場合は事前に S3 からエクスポートしてください
- **CDK Bootstrap スタック（`CDKToolkit`）は他の CDK プロジェクトでも使用する可能性があるため、削除対象から外しています**。完全にクリーンアップしたい場合のみ手動で削除してください
- **Bedrock Model Invocation Logging 設定**（`--enable-invocation-logging` で有効化していた場合）はアカウント・リージョン単位の設定のため、`SdpmData` 削除時に自動削除されます
