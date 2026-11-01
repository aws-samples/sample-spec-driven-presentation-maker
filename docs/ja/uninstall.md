[English](../en/uninstall.md) | [日本語](uninstall.md)

# アンインストールガイド

AWS アカウントから SDPM のリソースを削除する手順です。

## 概要

SDPM は複数の CloudFormation スタックをデプロイします。スタック同士に依存関係があるため、
CloudFormation コンソールから手で削除するのは手間がかかります。依存関係を考慮して一度に削除できる
[go-to-k/delstack](https://github.com/go-to-k/delstack) をおすすめします。

スタックの一覧（依存関係の逆順に削除）:

- `SdpmWebUi`（Layer 4）
- `SdpmAgent`（Layer 4）
- `SdpmRuntime`
- `SdpmData`
- `SdpmAuth`（既定の Cognito 構成を使っている場合）
- `SdpmCloudFrontWaf`（WAF を有効にした場合のみ。us-east-1 のみ）

**ワンクリックデプロイ** を使った場合は、Launch Stack ボタンが選んだリージョンに `SdpmDeploymentStack`
も作っています。中身はデプロイを動かすためのものだけです: CodeBuild プロジェクト、その IAM ロール
（`AdministratorAccess` 付き）、ビルドを開始する Lambda 関数、通知メール用の SNS トピック。このスタックを
削除しても上のアプリのスタックは消えず、アプリのスタックを削除してもこのスタックは残ります。アプリの
スタックを削除した後に、CloudFormation コンソールか `delstack --region <region> -s SdpmDeploymentStack`
で最後に削除してください。

## おすすめ: delstack を使う

[go-to-k/delstack](https://github.com/go-to-k/delstack) は、CloudFormation スタックを正しい依存関係の
順に削除し、消えにくいリソース（バージョニングされた S3 バケット、ECR リポジトリなど）も強制的に
片付けます。

### インストール

macOS / Linux:

```bash
brew install go-to-k/tap/delstack
```

Go で入れる場合:

```bash
go install github.com/go-to-k/delstack@latest
```

ほかのインストール方法は [delstack の README](https://github.com/go-to-k/delstack#install) にあります。

### 削除のコマンド

デプロイしたリージョン（例: `us-east-1`）で次を実行します。

```bash
# Delete Layer 4 full stack
delstack --region us-east-1 \
  -s SdpmWebUi \
  -s SdpmAgent \
  -s SdpmRuntime \
  -s SdpmData \
  -s SdpmAuth

# Add this if WAF was enabled (always us-east-1)
delstack --region us-east-1 -s SdpmCloudFrontWaf
```

Layer 3 のデプロイでは `SdpmWebUi` と `SdpmAgent` を省きます。

### delstack を使う理由

- **依存関係を自動で解決**: スタックを正しい順に削除します。
- **S3 バケットを強制削除**: バージョニングされたバケットも空にしてから削除します。
- **ECR リポジトリを強制削除**: そのままでは `DELETE_FAILED` になるリポジトリも扱えます。
- **対話で確認**: リソースの一覧を表示し、削除の前に `yes` の入力を求めます。

## AWS CloudShell から

AWS CloudShell には Go が入っているので、そこで delstack を入れて実行できます。

```bash
# Install in CloudShell
go install github.com/go-to-k/delstack@latest

# Put it on PATH
export PATH=$PATH:$(go env GOPATH)/bin

# Delete
delstack --region us-east-1 -s SdpmWebUi -s SdpmAgent -s SdpmRuntime -s SdpmData -s SdpmAuth
```

## CDK を使う（ローカル環境のみ）

ローカルに CDK の環境があれば、次のコマンドでも削除できます。

```bash
cd infra
npx cdk destroy --all
```

S3 バケットや ECR リポジトリにリソースが残っていると失敗しやすいため、こちらでも delstack をおすすめします。

## CloudFormation コンソールから手で削除する

GUI を使う場合は、スタックを **逆順** に削除します。

1. `SdpmWebUi`
2. `SdpmAgent`
3. `SdpmRuntime`
4. `SdpmData`
5. `SdpmAuth`
6. `SdpmCloudFrontWaf`（us-east-1 リージョンを確認）

S3 バケットや ECR リポジトリが残っていてスタックが `DELETE_FAILED` になった場合は、それらを手で空にしてから
もう一度削除します。

## 削除後の確認

次のリソースが残っていないことを確認します。

- CloudFormation: 上に挙げたスタック（ワンクリックデプロイの場合は `SdpmDeploymentStack` も）
- S3: `sdpm-*` または `cdk-*` で始まるバケット
- DynamoDB: `sdpm-*` のテーブル
- ECR: `sdpm-*` のリポジトリ
- SSM Parameter Store: `/sdpm/*`
- CloudWatch Logs: `/aws/lambda/sdpm-*`、`/aws/bedrock/*`

## 注意

- **この操作は元に戻せません。** 削除したデータは復元できないため、デッキやスライドを残したい場合は、先に S3 から書き出してください。
- **CDK のブートストラップスタック（`CDKToolkit`）** は、ほかの CDK プロジェクトと共有している場合があるため、
  意図的に対象外にしています。すべて片付けたい場合だけ、手で削除してください。
- **Bedrock のモデル呼び出しログ**（`--enable-invocation-logging` で有効化）はアカウント・リージョン単位の
  設定で、`SdpmData` の削除時に片付けられます。
