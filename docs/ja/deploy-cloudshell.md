[EN](../en/deploy-cloudshell.md) | [JA](../ja/deploy-cloudshell.md)

# spec-driven-presentation-maker CloudShell デプロイ手順

## spec-driven-presentation-maker について

spec-driven-presentation-maker は、AI エージェントにプレゼンテーション生成能力を追加するオープンソースツールキットです。MCP（Model Context Protocol）ツールとして既存の AI システムに接続するだけで、対話によるスライド生成が可能になります。ローカル CLI からフルスタック Web アプリまで、ニーズに合ったレイヤーを選んで段階的に採用できます。

spec-driven-presentation-maker を AWS CloudShell からデプロイする手順です。
ローカルに CDK や Docker は不要です。CodeBuild がすべてのビルド・デプロイを実行します。

## 前提条件

- AWS マネジメントコンソールにログイン済み
- デプロイ先アカウントで **AdministratorAccess** 相当の権限があること（初回デプロイ時）
- デプロイ先リージョンで CloudShell を開いていること

## 手順

### 1. CloudShell でリポジトリをクローンする

AWS コンソールで CloudShell を開き、リポジトリをクローンします。

```bash
cd ~
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
```

> **💡 ヒント:** CloudShell のホームディレクトリ（1 GB）はセッション間で永続化されます。2 回目以降は `cd ~/sample-spec-driven-presentation-maker && git pull` で最新化できます。

### 2. deploy.sh を実行する

```bash
chmod +x scripts/deploy.sh
```

用途に応じてオプションを選択します。

**Layer 4（フルスタック: Agent + Web UI）— デフォルト:**

> **🌐 ブラウザだけですぐに試したい方はこちら！** Layer 4 をデプロイすると、チャット形式の Web UI が立ち上がります。デプロイ後に [Cognito ユーザーを作成](#cognito-ユーザーの作成layer-4)すれば、ブラウザからすぐにスライド生成を体験できます。

```bash
./scripts/deploy.sh --region us-east-1
```

**Layer 3（MCP Server のみ）:**

```bash
./scripts/deploy.sh --region us-east-1 --layer3
```

**Bedrock Model Invocation Logging を有効化する場合:**

```bash
./scripts/deploy.sh --region us-east-1 --observability
```

> **注意:** `--observability` は Bedrock の Model Invocation Logging（MIL）をアカウント・リージョン単位で設定します。既に MIL が設定されている場合、スクリプトが既存設定の上書きについて警告し、確認を求めます。

**外部 IdP を使う場合:**

```bash
./scripts/deploy.sh --region us-east-1 \
  --oidc-url "https://your-idp.example.com/.well-known/openid-configuration" \
  --allowed-clients "client-id-1,client-id-2"
```

**スタックの削除:**

```bash
./scripts/deploy.sh --region us-east-1 --destroy
```

### 3. デプロイの進捗を確認する

スクリプトは CodeBuild のログをリアルタイムで表示します。
CloudShell のセッションがタイムアウトしても、CodeBuild のビルドは AWS 側で継続します。

セッションが切れた場合は、以下で結果を確認できます。

- **CodeBuild コンソール**: プロジェクト名 `sdpm-deploy` のビルド履歴
- **CloudFormation コンソール**: 各スタックのステータスと Outputs

### 4. デプロイ完了後の確認

ビルドが `SUCCEEDED` になると、CodeBuild のログ末尾に CloudFormation の Outputs が表示されます。
見逃した場合は CloudFormation コンソールから確認できます。

#### エンドポイント URL の確認

1. [CloudFormation コンソール](https://console.aws.amazon.com/cloudformation/) を開く
2. デプロイしたリージョンを選択

**Layer 3（MCP Server のみ）の場合:**

| スタック | Output キー | 内容 |
|---|---|---|
| `SdpmRuntime` | `RuntimeArn` | MCP Server の Runtime ARN |
| `SdpmRuntime` | `EndpointId` | Runtime Endpoint ID |

**Layer 4（フルスタック）の場合:**

| スタック | Output キー | 内容 |
|---|---|---|
| `SdpmAuth` | `UserPoolId` | Cognito User Pool ID |
| `SdpmAuth` | `UserPoolClientId` | Cognito App Client ID |
| `SdpmRuntime` | `RuntimeArn` | MCP Server の Runtime ARN |
| `SdpmAgent` | `AgentRuntimeArn` | Agent の Runtime ARN |
| `SdpmWebUi` | `SiteUrl` | Web UI の CloudFront URL |
| `SdpmWebUi` | `ApiUrl` | REST API の URL |

#### Cognito ユーザーの作成（Layer 4）

デフォルトの Cognito User Pool にはユーザーが存在しないため、手動で作成します。

1. [Cognito コンソール](https://console.aws.amazon.com/cognito/) を開く
2. User Pool 一覧から **sdpm-users** を選択
3. **Users** タブ → **Create user** をクリック
4. 以下を入力:
   - **Email address**: ログインに使うメールアドレス
   - **Temporary password**: 初回ログイン用の仮パスワード（8文字以上、大文字・数字を含む）
   - **Mark email address as verified** にチェック
5. **Create user** をクリック

#### Web UI にログインする

1. CloudFormation の `SdpmWebUi` スタック → Outputs → `SiteUrl` の URL をブラウザで開く
2. 作成したメールアドレスと仮パスワードでログイン
3. 初回ログイン時にパスワード変更を求められるので、新しいパスワードを設定
4. ログイン完了後、チャット画面が表示される

#### CLI からユーザーを作成する場合

CloudShell から直接作成することもできます。

```bash
REGION="us-east-1"
EMAIL="user@example.com"
TEMP_PASSWORD="<任意の仮パスワード>"  # 8文字以上、大文字・数字を含むこと

USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name SdpmAuth \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text --region "$REGION")

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
  --temporary-password "$TEMP_PASSWORD" \
  --region "$REGION"

SITE_URL=$(aws cloudformation describe-stacks \
  --stack-name SdpmWebUi \
  --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl`].OutputValue' \
  --output text --region "$REGION")

echo ""
echo "========================================="
echo "  ユーザー作成完了"
echo "========================================="
echo "  URL:      $SITE_URL"
echo "  Email:    $EMAIL"
echo "  Password: $TEMP_PASSWORD（初回ログイン時に変更）"
echo "========================================="
echo ""
echo "上記 URL にアクセスしてログインしてください。"
```

## オプション一覧

| オプション | 説明 | デフォルト |
|---|---|---|
| `--region REGION` | デプロイ先リージョン | `us-east-1` |
| `--profile PROFILE` | AWS CLI プロファイル | — |
| `--layer3` | Layer 3 のみ（MCP Server） | — |
| `--layer4` | Layer 4 フルスタック | デフォルト |
| `--search` | セマンティックスライド検索を有効化 | 無効 |
| `--observability` | Bedrock Model Invocation Logging を有効化 | 無効 |
| `--oidc-url URL` | 外部 IdP の OIDC Discovery URL | — |
| `--allowed-clients IDS` | JWT の許可クライアント ID（カンマ区切り） | — |
| `--destroy` | 全スタックを削除 | — |

## トラブルシューティング

**CodeBuild がタイムアウトする**

デフォルトのタイムアウトは 60 分です。初回デプロイで ECR イメージのビルドに時間がかかる場合があります。再実行すれば Docker レイヤーキャッシュが効いて速くなります。

**権限エラーが出る**

`deploy.sh` は CodeBuild のサービスロールに `AdministratorAccess` をアタッチします。IAM ロールの作成権限がない場合は、管理者にロール `sdpm-deploy-role` の事前作成を依頼してください。

**CloudShell のストレージが足りない**

CloudShell のホームディレクトリは 1 GB です。不要なファイルを削除してください。

```bash
# クローンし直す場合
rm -rf ~/sample-spec-driven-presentation-maker
```

**--observability で「既に設定済み」と警告される**

Bedrock Model Invocation Logging はアカウント・リージョンで 1 つしか設定できません。既存の設定がある場合、`deploy.sh` は上書きの確認を求めます。既存のログ送信先（CloudWatch Logs グループ名）が表示されるので、上書きして問題ないか確認してから `y` を入力してください。上書きすると、既存の MIL 設定は復元できません。

## 推定月額料金

> **2026 年 4 月時点の公開価格に基づく概算です。** AWS の各サービス料金は変更される可能性があります。最新の料金は各サービスの公式ページを参照してください: [Amazon Bedrock 料金](https://aws.amazon.com/bedrock/pricing/)、[AgentCore 料金](https://aws.amazon.com/bedrock/agentcore/pricing/)、[S3](https://aws.amazon.com/s3/pricing/)、[DynamoDB](https://aws.amazon.com/dynamodb/pricing/)。

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

### 合計

**月 $95〜145 程度**（利用量により変動）

### コスト削減のポイント

| 方法 | 削減額 | 備考 |
|---|---|---|
| プロンプトキャッシュ | LLM 費用最大 80% 削減 | 対応モデルではデフォルトで有効 |
| `--search` を付けない（デフォルト） | KB + S3 Vectors 費用なし | セマンティック検索が不要なら省略 |
| `--observability` を付けない（デフォルト） | CloudWatch Logs 費用なし | MIL ログの保存・転送費用が不要 |

## 関連ドキュメント

- [はじめに](getting-started.md) — Layer 1〜4 のセットアップ手順（ローカル CDK デプロイ含む）
- [アーキテクチャ](architecture.md) — 4 層構成、データフロー、認証モデル、MCP ツール一覧
- [カスタムテンプレート](custom-template.md) — テンプレートとアセットの追加
- [エージェント接続](add-to-gateway.md) — AgentCore Gateway への接続方法
- [Teams・Slack 連携](teams-slack-integration.md) — チャットプラットフォーム連携
